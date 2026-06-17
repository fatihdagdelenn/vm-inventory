"""
Zaman dilimi yardımcıları.

İlke: Veritabanında TÜM zaman damgaları UTC (naive) saklanır. Görüntüleme ve
zamanlanmış görevler için uygulama zaman dilimi (APP_TIMEZONE, vars. Europe/
Istanbul) uygulanır.

Neden gerekli: Önceden API, naive-UTC datetime'ları `.isoformat()` ile zaman
dilimi eki OLMADAN gönderiyordu. Tarayıcı eksiz ISO string'i *yerel saat*
sayıp evrensel anı kaydırıyordu (TR'de ~3 saat). Burada ISO çıktısına açık UTC
eki (+00:00) konur; tarayıcı doğru evrensel anı alır, ekranda istenen TZ'ye
çevrilir (bkz. app.js fmtDate + window.APP_TZ).
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from ..config import get_settings

UTC = timezone.utc


def app_tz() -> ZoneInfo:
    """Yapılandırılan uygulama zaman dilimi (geçersizse UTC'ye düşer)."""
    try:
        return ZoneInfo(get_settings().app_timezone)
    except Exception:
        return ZoneInfo("UTC")


def to_iso(dt: datetime | None) -> str | None:
    """
    Naive-UTC (veya aware) bir datetime'ı açık UTC ekli ISO string'e çevir.
    None ise None döner. Örn: 2026-06-16T07:00:00 -> '2026-06-16T07:00:00+00:00'
    """
    if dt is None:
        return None
    if dt.tzinfo is None:                 # naive değer UTC kabul edilir
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def now_local() -> datetime:
    """Uygulama zaman diliminde aware 'şimdi' (rapor başlığı, dosya adı, cron)."""
    return datetime.now(app_tz())
