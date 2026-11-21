"""Local time in German, as Pebbo speaks it."""

from __future__ import annotations

import os
import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

WEEKDAYS = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")
MONTHS = (
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
)  # fmt: skip
MAX_REMINDER_AHEAD = timedelta(days=366)


def timezone() -> ZoneInfo:
    return ZoneInfo(os.environ.get("PEBBO_TIMEZONE", "Europe/Zurich"))


def now() -> datetime:
    return datetime.now(timezone())


def spoken_datetime(moment: datetime, reference: datetime | None = None) -> str:
    """Say a point in time naturally, for example "morgen um 07:30" or "Freitag, 21. November um 18:00"."""
    reference = reference or now()
    moment = moment.astimezone(reference.tzinfo)
    clock = moment.strftime("%H:%M")
    days = (moment.date() - reference.date()).days
    if days == 0:
        return f"heute um {clock}"
    if days == 1:
        return f"morgen um {clock}"
    if days == 2:
        return f"übermorgen um {clock}"
    return f"{WEEKDAYS[moment.weekday()]}, {moment.day}. {MONTHS[moment.month - 1]} um {clock}"


def describe_now(reference: datetime | None = None) -> str:
    reference = reference or now()
    return (
        f"{WEEKDAYS[reference.weekday()]}, {reference.day}. {MONTHS[reference.month - 1]} {reference.year}, "
        f"{reference.strftime('%H:%M')} Uhr ({reference.tzinfo})"
    )


def parse_due(value: str, reference: datetime | None = None) -> datetime:
    """Parse a reminder time the model gives as local ISO 8601 and check it is plausible."""
    reference = reference or now()
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError as error:
        raise ValueError("Die Zeit muss im Format JJJJ-MM-TTTHH:MM angegeben werden.") from error
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=reference.tzinfo)
    if moment <= reference:
        raise ValueError("Dieser Zeitpunkt liegt in der Vergangenheit.")
    if moment - reference > MAX_REMINDER_AHEAD:
        raise ValueError("Erinnerungen gehen höchstens ein Jahr im Voraus.")
    return moment


def parse_clock_time(value: str) -> tuple[int, int]:
    """Read a time of day such as "07:30", "7 Uhr" or "2026-11-22T07:30" as ``(hour, minute)``."""
    text = value.strip()
    if "T" in text:
        text = text.split("T", 1)[1]
    match = re.search(r"(\d{1,2})(?:[:.h](\d{2}))?", text)
    if not match:
        raise ValueError("Die Uhrzeit muss im Format HH:MM angegeben werden.")
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    if hour == 24 and minute == 0:
        hour = 0
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError("Diese Uhrzeit gibt es nicht.")
    return hour, minute


def quiet_hours() -> tuple[time, time]:
    """The household's quiet hours from ``PEBBO_QUIET_HOURS`` ("22:00-07:00" by default)."""
    value = os.environ.get("PEBBO_QUIET_HOURS", "22:00-07:00")
    start, _, end = value.partition("-")
    try:
        return time(*parse_clock_time(start)), time(*parse_clock_time(end))
    except ValueError:
        return time(22, 0), time(7, 0)


def in_window(moment: datetime, start: time, end: time) -> bool:
    """Whether a local time lies in a daily window, which may run past midnight."""
    current = moment.timetz().replace(tzinfo=None, second=0, microsecond=0)
    if start <= end:
        return start <= current < end
    return current >= start or current < end


def in_quiet_hours(moment: datetime | None = None) -> bool:
    start, end = quiet_hours()
    return in_window(moment or now(), start, end)
