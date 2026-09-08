"""Waktu Indonesia Barat (WIB / Asia_Jakarta, GMT+7).

The database keeps naive UTC — that is what every `datetime.utcnow()` default
in models.py writes, and comparing stored values stays correct across a server
that might sit in any timezone. Everything a person reads or types is WIB, so
conversion happens exactly at those two edges:

    display   stored naive UTC  --to_wib()-->      aware WIB
    input     WIB text          --parse_local()--> stored naive UTC

Jakarta has had no DST since 1964 and a fixed +07:00 offset, so a fixed offset
is exact here and needs no tz database.
"""
from datetime import datetime, timedelta, timezone

WIB = timezone(timedelta(hours=7), "WIB")
TZ_LABEL = "WIB"
TZ_NAME = "Asia/Jakarta"
UTC_OFFSET_HOURS = 7


def now_utc():
    """Current moment as naive UTC — the form everything is stored in."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def now_wib():
    """Current moment as an aware WIB datetime."""
    return datetime.now(WIB)


def to_wib(value):
    """Naive-UTC (or aware) datetime -> aware WIB. Passes None straight through."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(WIB)


def to_utc(value):
    """Aware datetime -> naive UTC, ready to store."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def wib_to_utc(value):
    """A naive datetime a person entered in WIB -> naive UTC for storage."""
    if value is None:
        return None
    return to_utc(value.replace(tzinfo=WIB))


def parse_local(value, fmt="%Y-%m-%dT%H:%M"):
    """Parse a browser `datetime-local` / `date` value as WIB, return naive UTC.

    The browser sends whatever the person sees on their own clock, with no
    offset attached; reading it as UTC would shift every entry by seven hours.
    Returns None when the field is blank or malformed.
    """
    if not value:
        return None
    for candidate in (fmt, "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return wib_to_utc(datetime.strptime(value, candidate))
        except ValueError:
            continue
    return None


def to_input_value(value, fmt="%Y-%m-%dT%H:%M"):
    """Stored naive UTC -> the WIB string a `datetime-local` input expects."""
    local = to_wib(value)
    return local.strftime(fmt) if local else ""


def format_wib(value, fmt="%d %b %Y, %H:%M"):
    local = to_wib(value)
    return local.strftime(fmt) if local else "-"
