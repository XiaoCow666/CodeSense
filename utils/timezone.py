"""Application timezone helpers.

Database timestamps are stored as naive UTC values for compatibility with the
existing schema.  User-facing timestamps must therefore be converted before
they are rendered.
"""

import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_DISPLAY_TIMEZONE = "Asia/Shanghai"


def _display_timezone():
    configured = (
        os.environ.get("DISPLAY_TIMEZONE", DEFAULT_DISPLAY_TIMEZONE).strip()
        or DEFAULT_DISPLAY_TIMEZONE
    )
    try:
        return ZoneInfo(configured)
    except ZoneInfoNotFoundError:
        # Windows installations may not ship the IANA zoneinfo database.  Keep
        # the configured production default usable without adding a dependency.
        if configured == DEFAULT_DISPLAY_TIMEZONE:
            return timezone(timedelta(hours=8), name=DEFAULT_DISPLAY_TIMEZONE)
        return timezone.utc


DISPLAY_TIMEZONE = _display_timezone()


def to_display_datetime(value):
    """Convert a stored UTC datetime to the configured display timezone."""

    if value is None or not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(DISPLAY_TIMEZONE)


def format_display_datetime(value, fmt="%Y-%m-%d %H:%M:%S"):
    """Return a user-facing local timestamp, or an empty string for null."""

    if value is None:
        return ""
    converted = to_display_datetime(value)
    return converted.strftime(fmt) if isinstance(converted, datetime) else str(converted)
