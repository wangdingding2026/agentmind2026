from datetime import datetime, timezone


def test_to_local_display_converts_utc_sqlite_to_shanghai_time():
    from agentmind.services.time_service import to_local_display

    assert to_local_display("2026-05-29 09:52:21") == "2026-05-29 17:52"


def test_local_day_bounds_for_today_use_configured_timezone():
    from agentmind.services.time_service import local_day_bounds

    now = datetime(2026, 5, 29, 10, 12, 14, tzinfo=timezone.utc)

    start, end = local_day_bounds("today", now=now)

    assert start == "2026-05-28 16:00:00"
    assert end == "2026-05-29 15:59:59"


def test_local_date_key_groups_utc_storage_by_shanghai_day():
    from agentmind.services.time_service import local_date_key

    assert local_date_key("2026-05-28 16:30:00") == "2026-05-29"
