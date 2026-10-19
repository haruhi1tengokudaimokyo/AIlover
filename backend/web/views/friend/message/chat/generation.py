"""Single-process generation ownership; no prompts or audio retained here."""
import threading
import time
from collections import OrderedDict

_guard = threading.Lock()
_active = {}
_completed = OrderedDict()


class Generation:
    def __init__(self, friend_id, ident, lease=None):
        self.friend_id, self.id, self.lease = friend_id, ident, lease
        self.stopped, self.done = threading.Event(), threading.Event()
        self.worker_done = threading.Event()
        self.stream_closed = False
        self.started = False
        self.guard = threading.Lock()
        self.created = time.monotonic()
        self.metrics = {'ttft_ms': None, 'ttfa_ms': None, 'model_ms': None, 'tts_ms': None,
                        'queue_wait_count': 0, 'queue_wait_total_ms': 0, 'queue_wait_max_ms': 0,
                        'audio_chunks': 0, 'sentence_count': 0, 'errors': [], 'cancelled': False,
                        'cleanup_complete': False}

    def activate(self):
        with self.guard:
            if self.stopped.is_set() or self.done.is_set():
                return False
            self.started = True
            return True

    def cancel(self):
        with self.guard:
            if self.done.is_set():
                return
            self.metrics['cancelled'] = True
            self.stopped.set()
            inactive = not self.started
        if inactive:
            self.finish()
            self.close_stream()

    def finish(self):
        with self.guard:
            self.worker_done.set()
            self.metrics['cleanup_complete'] = 'llm_client_close_failed' not in self.metrics['errors']
        self._complete_if_ready()

    def close_stream(self):
        with self.guard:
            self.stream_closed = True
        self._complete_if_ready()

    def _complete_if_ready(self):
        with self.guard:
            if self.done.is_set() or not self.worker_done.is_set() or not self.stream_closed:
                return
            if self.lease:
                self.lease.release()
            self.metrics['complete_ms'] = (time.monotonic() - self.created) * 1000
            self.done.set()
        with _guard:
            if _active.get(self.friend_id) is self:
                del _active[self.friend_id]
            _completed[(self.friend_id, self.id)] = time.monotonic()
            while len(_completed) > 256:
                _completed.popitem(last=False)


def register(generation):
    with _guard:
        instant = time.monotonic()
        for key, stamp in list(_completed.items()):
            if instant - stamp > 300:
                del _completed[key]
        if generation.friend_id in _active or (generation.friend_id, generation.id) in _completed:
            raise ValueError('generation_already_used')
        _active[generation.friend_id] = generation


def cancel(friend_id, ident):
    with _guard:
        generation = _active.get(friend_id)
        if generation is None or generation.id != ident:
            return None
    generation.cancel()
    return generation
