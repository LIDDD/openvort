"""Datetime utilities."""

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _org_tz() -> ZoneInfo:
    """Resolve organization timezone (defaults to Asia/Shanghai)."""
    tz_name = "Asia/Shanghai"
    try:
        from openvort.config.settings import get_settings

        tz_name = get_settings().org.timezone or tz_name
    except Exception:
        pass
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("Asia/Shanghai")


def naive_local_to_epoch(dt: datetime | None) -> float:
    """Convert a DB naive datetime (assumed to be in org-local timezone) to epoch seconds.

    PG TIMESTAMP WITHOUT TIME ZONE columns store wall-clock values in the server timezone,
    which by convention matches OPENVORT_ORG_TIMEZONE. ``datetime.timestamp()`` on a naive
    value uses the host process timezone, so containers running in UTC produce results that
    are 8 hours off from the intended local epoch. Anchor the timezone explicitly here.
    """
    if dt is None:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_org_tz())
    return dt.timestamp()
