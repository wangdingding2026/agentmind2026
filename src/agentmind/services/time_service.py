"""Timezone helpers for UTC storage and local display boundaries."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "Asia/Shanghai"


def get_display_timezone(settings: dict | None = None) -> str:
    if isinstance(settings, dict):
        value = settings.get("timezone") or settings.get("display_timezone")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return DEFAULT_TIMEZONE


def parse_utc(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value or "").strip()
        if not text:
            return datetime.fromtimestamp(0, timezone.utc)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        if "T" in text:
            dt = datetime.fromisoformat(text)
        else:
            dt = datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_local(value: str | datetime, timezone_name: str = DEFAULT_TIMEZONE) -> datetime:
    return parse_utc(value).astimezone(ZoneInfo(timezone_name))


def to_local_display(value: str | datetime, timezone_name: str = DEFAULT_TIMEZONE) -> str:
    return to_local(value, timezone_name).strftime("%Y-%m-%d %H:%M")


def local_date_key(value: str | datetime, timezone_name: str = DEFAULT_TIMEZONE) -> str:
    return to_local(value, timezone_name).strftime("%Y-%m-%d")


def local_day_bounds(
    day: str,
    *,
    now: datetime | None = None,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> tuple[str, str]:
    tz = ZoneInfo(timezone_name)
    current = (now or datetime.now(timezone.utc)).astimezone(tz)
    if day == "yesterday":
        target = current.date() - timedelta(days=1)
    else:
        target = current.date()
    start_local = datetime.combine(target, time.min, tzinfo=tz)
    end_local = datetime.combine(target, time.max, tzinfo=tz).replace(microsecond=0)
    return (
        start_local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        end_local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    )
