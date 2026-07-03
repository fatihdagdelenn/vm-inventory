"""
Lightweight, dependency-free event broadcast (in-process pub/sub).
Bridges the background sync thread (sync_service) with SSE subscribers.
"""
import time
import threading
import itertools
from collections import deque

_LOCK = threading.Lock()
_BUF = deque(maxlen=500)
_SEQ = itertools.count(1)


def publish(event: dict) -> None:
    """Append an event to the buffer (called by sync_service). Never raises."""
    try:
        with _LOCK:
            _BUF.append((next(_SEQ), time.time(), dict(event)))
    except Exception:
        pass


def read_since(last_seq: int):
    """Return events with seq > last_seq as [(seq, ts, event), ...]."""
    with _LOCK:
        return [item for item in _BUF if item[0] > last_seq]


def latest_seq() -> int:
    """Latest seq in the buffer (new subscribers start here -> no replay)."""
    with _LOCK:
        return _BUF[-1][0] if _BUF else 0
