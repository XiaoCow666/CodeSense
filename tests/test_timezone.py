from datetime import datetime, timezone

from utils.timezone import format_display_datetime


def test_format_display_datetime_converts_naive_utc_to_shanghai():
    value = datetime(2026, 9, 4, 5, 33, 19)

    assert format_display_datetime(value) == "2026-09-04 13:33:19"


def test_format_display_datetime_preserves_explicit_timezone_conversion():
    value = datetime(2026, 9, 4, 5, 33, 19, tzinfo=timezone.utc)

    assert format_display_datetime(value, "%Y-%m-%d %H:%M") == "2026-09-04 13:33"
