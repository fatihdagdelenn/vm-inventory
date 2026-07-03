"""
Timezone helpers.
Policy: ALL timestamps are stored naive UTC in the database. Display and
scheduled jobs apply the configured app timezone.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from ..config import get_settings

UTC = timezone.utc


def app_tz() -> ZoneInfo:
    """The configured app timezone (falls back to UTC when invalid)."""
    try:
        return ZoneInfo(get_settings().app_timezone)
    except Exception:
        return ZoneInfo("UTC")


def to_iso(dt: datetime | None) -> str | None:
    """
        Convert a naive-UTC (or aware) datetime to an ISO string with explicit UTC.
        None in, None out. E.g. 2026-06-16T07:00:00+00:00.
        """
    if dt is None:
        return None
    if dt.tzinfo is None:                 # naive values are treated as UTC
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def now_local() -> datetime:
    """Aware 'now' in the app timezone (report titles, filenames, cron)."""
    return datetime.now(app_tz())
