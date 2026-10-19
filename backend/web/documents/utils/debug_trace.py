"""Bounded metadata-only diagnostic snapshots; gated by server development flag."""
import copy
import os
import threading
import time
from collections import OrderedDict
from django.conf import settings

_snapshots = OrderedDict()
_guard = threading.Lock()


def enabled():
    return settings.DEBUG and os.getenv('ROLEPLAY_DEBUG_TRACE', 'false').lower() == 'true'


def save(friend_id, generation_id, trace, metrics=None):
    if not enabled():
        return
    with _guard:
        _snapshots[(friend_id, generation_id)] = (time.monotonic(), copy.deepcopy(trace), copy.deepcopy(metrics))
        _snapshots.move_to_end((friend_id, generation_id))
        while len(_snapshots) > 128:
            _snapshots.popitem(last=False)


def read(friend_id, generation_id):
    if not enabled():
        return None
    with _guard:
        item = _snapshots.get((friend_id, generation_id))
        if not item or time.monotonic() - item[0] > 900:
            _snapshots.pop((friend_id, generation_id), None)
            return None
        return copy.deepcopy({'trace': item[1], 'metrics': item[2]})
