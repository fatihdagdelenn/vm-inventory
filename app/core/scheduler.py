"""
Arka plan zamanlayıcısı (APScheduler).

Performans stratejisi:
- vCenter/Proxmox API'leri SADECE buradaki zamanlanmış görevlerle sorgulanır.
- Sonuçlar lokal veritabanına yazılır (cache).
- Kullanıcı aramaları/sayfaları hiçbir zaman canlı API çağrısı tetiklemez.
- Varsayılan aralık SYNC_INTERVAL_MINUTES (15 dk), .env'den ayarlanabilir.
"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from ..config import get_settings

logger = logging.getLogger("scheduler")


def _scheduler_tz() -> str:
    """Yapılandırılan TZ adını döndür; geçerli değilse UTC'ye düş."""
    tz = get_settings().app_timezone
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(tz)        # ad gerçekten çözülebiliyor mu?
        return tz
    except Exception:
        logger.warning("Geçersiz APP_TIMEZONE=%r, UTC kullanılıyor", tz)
        return "UTC"


# Cron tabanlı zamanlanmış raporların doğru YEREL saatte çalışması için
# zamanlayıcı uygulama zaman dilimiyle kurulur (eskiden UTC idi).
scheduler = BackgroundScheduler(timezone=_scheduler_tz())


def start_scheduler():
    """Uygulama açılışında çağrılır; periyodik senkronizasyon görevini kurar."""
    from ..services.sync_service import sync_all_platforms, sync_usage_all

    settings = get_settings()
    scheduler.add_job(
        sync_all_platforms,
        trigger="interval",
        minutes=settings.sync_interval_minutes,
        id="sync_all",
        max_instances=1,        # çakışan senkronizasyonları engelle
        coalesce=True,          # kaçırılan çalıştırmaları birleştir
        replace_existing=True,
    )
    # Hafif kullanım tazelemesi: tam senkronizasyondan bağımsız, çok daha sık.
    # Tek/az API çağrısı yaptığı için canlı ortama yük bindirmez.
    scheduler.add_job(
        sync_usage_all,
        trigger="interval",
        minutes=settings.usage_sync_interval_minutes,
        id="usage_sync",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    # Açılıştan kısa süre sonra bir kez hemen çalıştır: kullanıcı,
    # konteyner yeniden başlatıldıktan sonra kullanım verisini görmek
    # için ilk aralığı (3 dk) beklemek zorunda kalmasın.
    from datetime import timedelta
    from .timezone import now_local
    scheduler.add_job(
        sync_usage_all,
        trigger="date",
        run_date=now_local() + timedelta(seconds=20),   # aware (scheduler TZ ile uyumlu)
        id="usage_sync_boot",
        replace_existing=True,
    )
    scheduler.start()
    # Kalıcı zamanlanmış raporları DB'den scheduler'a geri yükle.
    # (Eskiden bellek-içi tutuldukları için her yeniden başlatmada kayboluyorlardı.)
    try:
        from ..api.reports import register_all_scheduled_reports
        register_all_scheduled_reports()
    except Exception as exc:
        logger.warning("Zamanlanmış raporlar yüklenemedi: %s", exc)
    logger.info("Zamanlayıcı başlatıldı: tam senkr. %s dk, kullanım tazeleme %s dk",
                settings.sync_interval_minutes, settings.usage_sync_interval_minutes)


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
