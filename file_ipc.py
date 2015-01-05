import os
import logging
import tempfile
import json

PERMDIR = os.getenv('NBE_PERMDIR', tempfile.gettempdir())
INSTANCE_FILE = os.path.join(PERMDIR, 'instances.json')
INSTANCE_INTERMEDIA_FILE = os.path.join(PERMDIR, 'instances.tmp.json')


def write(nodes):
    with open(INSTANCE_INTERMEDIA_FILE, 'w') as f:
        f.write(json.dumps(nodes))
    os.rename(INSTANCE_INTERMEDIA_FILE, INSTANCE_FILE)


def read():
    try:
        with open(INSTANCE_FILE, 'r') as f:
            return json.loads(f.read())
    except IOError, e:
        logging.exception(e)
        return []

POLL_FILE = os.path.join(PERMDIR, 'poll.json')
POLL_INTERMEDIA_FILE = os.path.join(PERMDIR, 'poll.tmp.json')


def write_poll(nodes):
    with open(POLL_INTERMEDIA_FILE, 'w') as f:
        f.write(json.dumps(nodes))
    os.rename(POLL_INTERMEDIA_FILE, POLL_FILE)


def read_poll():
    try:
        with open(POLL_FILE, 'r') as f:
            return json.loads(f.read())
    except IOError, e:
        logging.exception(e)
        return []
