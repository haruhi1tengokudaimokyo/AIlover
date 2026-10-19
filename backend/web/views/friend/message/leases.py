"""桌面单进程服务内，每个好友会话只能有一个写入任务。"""
import threading
from weakref import WeakValueDictionary

_locks = WeakValueDictionary()
_guard = threading.Lock()


class Lease:
    def __init__(self, lock):
        self.lock = lock
        self.released = False
        self.guard = threading.Lock()

    def release(self):
        with self.guard:
            if not self.released:
                self.released = True
                self.lock.release()


def acquire(friend_id):
    with _guard:
        lock = _locks.get(friend_id)
        if lock is None:
            lock = threading.Lock()
            _locks[friend_id] = lock
        if not lock.acquire(blocking=False):
            return None
        return Lease(lock)
