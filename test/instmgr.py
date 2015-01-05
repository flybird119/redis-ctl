import unittest

from test_utils import testdb
import redisctl.instance_manage as im
import redisctl.cluster as clu
import redisctl.db
import redisctl.errors

COL_HOST = redisctl.instance_manage.COL_HOST
COL_PORT = redisctl.instance_manage.COL_PORT
COL_CLUSTER_ID = redisctl.instance_manage.COL_CLUSTER_ID


class InstanceManagement(unittest.TestCase):
    def setUp(self):
        testdb.reset_db()

    def test_request_instance(self):
        with redisctl.db.update() as client:
            im.create_instance(client, '10.1.201.10', 9000, 536870912)
            im.create_instance(client, '10.1.201.10', 9001, 1000000000)
            im.create_instance(client, '10.1.201.12', 6376, 536870912)
            cluster_id = clu.create_cluster(client, 'forgot-me-not')

        with redisctl.db.query() as client:
            client.execute('''SELECT * FROM `redis_node`''')
            i = sorted(list(client.fetchall()), key=lambda x: (
                x[COL_HOST], x[COL_HOST]))
            self.assertEqual(3, len(i))
            self.assertEqual(('10.1.201.10', 9000, 536870912L, 0, None, None),
                             i[0][1:])
            self.assertEqual(('10.1.201.10', 9001, 1000000000L, 0, None, None),
                             i[1][1:])
            self.assertEqual(('10.1.201.12', 6376, 536870912L, 0, None, None),
                             i[2][1:])

        im.pick_and_launch('10.1.201.10', 9000, cluster_id, lambda _, __: None)

        with redisctl.db.query() as client:
            client.execute('''SELECT `id` FROM `redis_node`
                WHERE `occupier_id` IS NOT NULL LIMIT 1''')
            self.assertIsNone(client.fetchone())

            client.execute('''SELECT * FROM `redis_node`
                WHERE `assignee_id` IS NOT NULL''')
            r = list(client.fetchall())
            self.assertEqual(1, len(r))
            r = r[0]
            self.assertEqual('10.1.201.10', r[COL_HOST])
            self.assertEqual(9000, r[COL_PORT])
            cluster_id = r[COL_CLUSTER_ID]

            client.execute('''SELECT * FROM `cluster`''')
            r = list(client.fetchall())
            self.assertEqual(1, len(r))
            r = r[0]
            self.assertEqual(cluster_id, r[0])

    def test_instance_occupied(self):
        with redisctl.db.update() as client:
            im.create_instance(client, '10.1.201.10', 9000, 536870912)
            im.create_instance(client, '10.1.201.10', 9001, 536870912)
            cluster_id = clu.create_cluster(client, 'eternal-rite')

        with redisctl.db.update() as client:
            # Manully update to make the application occupying
            client.execute('''SELECT `id`,`port` FROM `redis_node` LIMIT 1''')
            inst = client.fetchone()
            inst_id = inst[0]
            client.execute('''UPDATE `redis_node` SET `occupier_id`=%s
                WHERE `id`=%s''', (cluster_id, inst_id))
            test_port = 9001 if inst[1] == 9000 else 9000

        self.assertRaises(redisctl.errors.AppMutexError, im.pick_and_launch,
                          '10.1.201.10', test_port, cluster_id,
                          lambda _, __: None)
