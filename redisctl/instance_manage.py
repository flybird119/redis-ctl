import socket
import json
import logging
import redistrib.communicate as comm

import db


# Assume result in format
# [
#   { host: 10.1.201.10, port: 9000, max_mem: 536870912 },
#   { host: 10.1.201.10, port: 9001, max_mem: 536870912 },
#   ...
# ]
def _fetch_redis_instance_pool(host, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((host, port))
    try:
        s.sendall('psy-el-congroo')
        return json.loads(s.recv(4096))
    finally:
        s.close()

COL_ID = 0
COL_HOST = 1
COL_PORT = 2
COL_MEM = 3
COL_STAT = 4
COL_APPID = 5
STATUS_ONLINE = 0
STATUS_MISSING = -1
STATUS_BROKEN = -2
STATUS_BUSY = 1


def _create_instance(client, host, port, max_mem):
    client.execute('''INSERT INTO `cache_instance`
        (`host`, `port`, `max_mem`, `status`, `assignee_id`)
        VALUES (%s, %s, %s, 0, null)''', (host, port, max_mem))


def _flag_instance(client, instance_id, status):
    client.execute('''UPDATE `cache_instance` SET `status`=%s WHERE `id`=%s''',
                   (status, instance_id))


def _update_status(client, instance_id, max_mem):
    client.execute('''UPDATE `cache_instance`
        SET `status`=0, `max_mem`=%s WHERE `id`=%s''', (max_mem, instance_id))


def _remove(client, instance_id):
    client.execute('''DELETE FROM `cache_instance` WHERE `id`=%s''',
                   (instance_id,))


def _pick_by_app(client, app_id):
    client.execute('''SELECT * FROM `cache_instance`
        WHERE `assignee_id`=%s LIMIT 1''', app_id)
    return client.fetchone()


def _pick_available(client):
    client.execute('''SELECT * FROM `cache_instance`
        WHERE ISNULL(`assignee_id`) LIMIT 1''')
    return client.fetchone()


def _distribute_to_app(client, instance_id, app_id):
    client.execute('''UPDATE `cache_instance` SET `assignee_id`=%s
        WHERE `id`=%s AND ISNULL(`assignee_id`)''', (app_id, instance_id))


def _get_id_from_app_or_none(client, app_name):
    client.execute('''SELECT `id` FROM `application`
        WHERE `app_name`=%s LIMIT 1''', app_name)
    r = client.fetchone()
    return None if r is None else r[0]


def _get_id_from_app(client, app_name):
    r = _get_id_from_app_or_none(client, app_name)
    if r is not None:
        return r

    client.execute('''INSERT INTO `application` (`app_name`) VALUES (%s)''',
                   (app_name,))
    return client.lastrowid


class InstanceManager(object):
    def _sync_instance_status(self):
        remote_instances = _fetch_redis_instance_pool(
            self.remote_host, self.remote_port)
        saved_instances = InstanceManager._load_saved_instaces()

        newly = []
        update = dict()
        for ri in remote_instances:
            si = saved_instances.get((ri['host'], ri['port']))
            if si is None:
                newly.append(ri)
                continue
            if si[COL_STAT] != STATUS_ONLINE or si[COL_MEM] != ri['max_mem']:
                update[si[COL_ID]] = ri
            del saved_instances[(ri['host'], ri['port'])]
        with db.update() as client:
            for i in newly:
                _create_instance(client, i['host'], i['port'], i['max_mem'])
            for instance_id, i in update.iteritems():
                _update_status(client, instance_id, i['max_mem'])
            for other_instance in saved_instances.itervalues():
                if other_instance[COL_APPID] is None:
                    _remove(client, other_instance[COL_ID])
                else:
                    _flag_instance(client, other_instance[COL_ID],
                                   STATUS_MISSING)

    @staticmethod
    def _load_saved_instaces():
        with db.query() as client:
            client.execute('''SELECT * FROM `cache_instance`''')
            return {(i[COL_HOST], i[COL_PORT]): i for i in client.fetchall()}

    def __init__(self, remote_host, remote_port, start_cluster, join_node):
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.start_cluster = start_cluster
        self.join_node = join_node

        self._sync_instance_status()

    def app_start(self, appname):
        self._sync_instance_status()
        with db.update() as client:
            app_id = _get_id_from_app(client, appname)
            instance = _pick_by_app(client, app_id)
            if instance is not None:
                return {
                    'host': instance[COL_HOST],
                    'port': instance[COL_PORT],
                }
        return self.pick_and_launch(app_id)

    def pick_and_launch(self, app_id):
        while True:
            with db.update() as client:
                instance = _pick_available(client)
                if instance is None:
                    raise ValueError('No available instance')
                try:
                    self.start_cluster(instance[COL_HOST], instance[COL_PORT])
                except comm.RedisStatusError, e:
                    logging.exception(e)
                    _flag_instance(client, instance[COL_ID], STATUS_BROKEN)
                    continue

                _distribute_to_app(client, instance[COL_ID], app_id)
            return {
                'host': instance[COL_HOST],
                'port': instance[COL_PORT],
            }

    def app_expand(self, appname):
        self._sync_instance_status()
        while True:
            with db.update() as client:
                app_id = _get_id_from_app_or_none(client, appname)
                if app_id is None:
                    raise ValueError(
                        'Application [ %s ] not registered' % appname)
                cluster = _pick_by_app(client, app_id)
                new_node = _pick_available(client)
                if new_node is None:
                    raise ValueError('No available instance')
                try:
                    self.join_node(cluster[COL_HOST], cluster[COL_PORT],
                                   new_node[COL_HOST], new_node[COL_PORT])
                except comm.RedisStatusError, e:
                    logging.exception(e)
                    _flag_instance(client, new_node[COL_ID], STATUS_BROKEN)
                    continue

                return _distribute_to_app(client, new_node[COL_ID], app_id)
