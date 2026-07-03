"""
Background scheduler (APScheduler).
Performance strategy:
- vCenter/Proxmox APIs are hit ONLY by the scheduled jobs here (and manual
  refresh); user searches always read the local DB.
"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from ..config import get_settings

logger = logging.getLogger("scheduler")


def _scheduler_tz() -> str:
    """Return the configured TZ name; fall back to UTC when invalid."""
    tz = get_settings().app_timezone
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(tz)        # can the name actually be resolved?
        return tz
    except Exception:
        logger.warning("Invalid APP_TIMEZONE=%r, using UTC", tz)
        return "UTC"


# The scheduler is built with the app timezone so cron-based scheduled
# reports run at the correct LOCAL time (used to be UTC).
scheduler = BackgroundScheduler(timezone=_scheduler_tz())


def _db_intervals():
    """Read sync intervals from the DB; fall back to .env defaults."""
    settings = get_settings()
    full, usage = settings.sync_interval_minutes, settings.usage_sync_interval_minutes
    try:
        from ..database import SessionLocal
        from .app_settings import get_int_setting
        db = SessionLocal()
        try:
            full = max(1, get_int_setting(db, "sync_interval_minutes", full))
            usage = max(1, get_int_setting(db, "usage_sync_interval_minutes", usage))
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Could not read intervals from DB, using defaults: %s", exc)
    return full, usage


def reschedule_sync(full_min=None, usage_min=None):
    """Reschedule jobs when an interval changes in the UI (no restart)."""
    if full_min:
        scheduler.reschedule_job("sync_all", trigger="interval", minutes=int(full_min))
    if usage_min:
        scheduler.reschedule_job("usage_sync", trigger="interval", minutes=int(usage_min))
    logger.info("Sync rescheduled: full=%s min, usage=%s min",
                full_min, usage_min)


def start_scheduler():
    """Called on app startup; installs the periodic sync jobs."""
    from ..services.sync_service import sync_all_platforms, sync_usage_all

    full_min, usage_min = _db_intervals()
    scheduler.add_job(
        sync_all_platforms,
        trigger="interval",
        minutes=full_min,
        id="sync_all",
        max_instances=1,        # prevent overlapping syncs
        coalesce=True,          # coalesce missed runs
        replace_existing=True,
    )
    # Lightweight usage refresh: independent of the full sync, much more frequent.
    # One/few API calls, so it puts no load on the live environment.
    scheduler.add_job(
        sync_usage_all,
        trigger="interval",
        minutes=usage_min,
        id="usage_sync",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    # Run once shortly after startup: the user should not have to wait
    # the first interval (3 min) to see usage data after the container
    # restarts.
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
    # Reload persistent scheduled reports from the DB into the scheduler.
    # (They used to be in-memory and were lost on every restart.)
    try:
        from ..api.reports import register_all_scheduled_reports
        register_all_scheduled_reports()
    except Exception as exc:
        logger.warning("Could not load scheduled reports: %s", exc)
    logger.info("Scheduler started: full sync %s min, usage refresh %s min",
                full_min, usage_min)


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
