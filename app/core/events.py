"""
Hafif, bağımlılıksız olay yayını (in-process pub/sub).

Arka plan iş parçacığındaki senkronizasyon (sync_service) ile asenkron SSE
uç noktası (api/topology.py) arasında köprü kurar. Cross-thread asyncio.Queue
karmaşası yerine, sıralı (monotonik seq) bir ring-buffer kullanır; SSE üreteci
periyodik olarak "son gördüğüm seq'ten sonrası"nı okur.

Kalıcılık YOK — yalnız anlık canlı bildirim içindir (kaçırılan olaylar bir
sonraki periyodik tam senkronizasyonla zaten yansır).
"""
import time
import threading
import itertools
from collections import deque

_LOCK = threading.Lock()
_BUF = deque(maxlen=500)
_SEQ = itertools.count(1)


def publish(event: dict) -> None:
    """Bir olayı tampona ekle (sync_service çağırır). Asla exception fırlatmaz."""
    try:
        with _LOCK:
            _BUF.append((next(_SEQ), time.time(), dict(event)))
    except Exception:
        pass


def read_since(last_seq: int):
    """last_seq'ten büyük seq'li olayları [(seq, ts, event), ...] döndür."""
    with _LOCK:
        return [item for item in _BUF if item[0] > last_seq]


def latest_seq() -> int:
    """Tampondaki en son seq (yeni abone buradan başlar → eski olayları tekrar etmez)."""
    with _LOCK:
        return _BUF[-1][0] if _BUF else 0
