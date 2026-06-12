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
scheduler = BackgroundScheduler(timezone="UTC")


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
    from datetime import datetime, timedelta
    scheduler.add_job(
        sync_usage_all,
        trigger="date",
        run_date=datetime.utcnow() + timedelta(seconds=20),
        id="usage_sync_boot",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Zamanlayıcı başlatıldı: tam senkr. %s dk, kullanım tazeleme %s dk",
                settings.sync_interval_minutes, settings.usage_sync_interval_minutes)


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
