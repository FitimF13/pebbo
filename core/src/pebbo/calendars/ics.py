"""A small, permissive iCalendar (RFC 5545) reader for subscribed calendars.

It reads what briefings need from ``VEVENT`` entries: ``UID``, ``SUMMARY``, ``DTSTART``,
``DTEND`` or ``DURATION``, ``RRULE`` and ``EXDATE``. Recurrence supports the common rules:
``FREQ`` daily, weekly, monthly and yearly with ``INTERVAL``, ``COUNT``, ``UNTIL`` and, for
weekly rules, ``BYDAY``. Anything else is ignored rather than rejected, so a calendar with
unusual entries still shows its ordinary appointments.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
_DURATION = re.compile(
    r"^(?P<sign>[+-])?P(?:(?P<weeks>\d+)W)?(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)
# Never expand more occurrences than this from one rule.
MAX_OCCURRENCES = 2000


@dataclass(frozen=True)
class IcsEvent:
    uid: str
    title: str
    start: datetime
    end: datetime | None
    all_day: bool
    rrule: str | None = None
    exdates: tuple[datetime, ...] = field(default_factory=tuple)


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw.strip():
            lines.append(raw)
    return lines


def _split(line: str) -> tuple[str, dict[str, str], str]:
    """``NAME;PARAM=value:content`` as name, parameters and content."""
    head, _, value = line.partition(":")
    # A colon inside a quoted parameter belongs to the parameter.
    while head.count('"') % 2 == 1 and value:
        more, _, value = value.partition(":")
        head += ":" + more
    name, *params = head.split(";")
    parameters: dict[str, str] = {}
    for param in params:
        key, _, param_value = param.partition("=")
        parameters[key.upper()] = param_value.strip('"')
    return name.upper(), parameters, value


def unescape(value: str) -> str:
    return re.sub(r"\\([\\;,nN])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), value).strip()


def _zone(name: str | None, fallback: tzinfo) -> tzinfo:
    if not name:
        return fallback
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return fallback


def parse_value(value: str, parameters: dict[str, str], fallback: tzinfo) -> tuple[datetime, bool]:
    """A ``DATE`` or ``DATE-TIME`` value as an aware datetime, and whether it is a whole day."""
    value = value.strip()
    if parameters.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        day = datetime.strptime(value[:8], "%Y%m%d").date()
        return datetime.combine(day, time(), fallback), True
    utc = value.endswith("Z")
    moment = datetime.strptime(value.rstrip("Z")[:15], "%Y%m%dT%H%M%S")
    if utc:
        return moment.replace(tzinfo=UTC).astimezone(fallback), False
    return moment.replace(tzinfo=_zone(parameters.get("TZID"), fallback)), False


def parse_duration(value: str) -> timedelta | None:
    match = _DURATION.match(value.strip())
    if not match:
        return None
    parts = {key: int(number) for key, number in match.groupdict().items() if key != "sign" and number}
    delta = timedelta(
        weeks=parts.get("weeks", 0),
        days=parts.get("days", 0),
        hours=parts.get("hours", 0),
        minutes=parts.get("minutes", 0),
        seconds=parts.get("seconds", 0),
    )
    return -delta if match.group("sign") == "-" else delta


def parse_ics(text: str, zone: tzinfo) -> list[IcsEvent]:
    """All events of a calendar. ``zone`` is used for floating times and unknown time zones."""
    events: list[IcsEvent] = []
    current: dict[str, tuple[dict[str, str], str]] | None = None
    exdates: list[tuple[dict[str, str], str]] = []
    depth = 0
    for line in _unfold(text):
        name, parameters, value = _split(line)
        if name == "BEGIN" and value.upper() == "VEVENT":
            current, exdates, depth = {}, [], 0
            continue
        if current is None:
            continue
        if name == "BEGIN":
            depth += 1  # A nested VALARM, whose properties are not the event's.
        elif name == "END" and value.upper() == "VEVENT":
            event = _event(current, exdates, zone)
            if event is not None:
                events.append(event)
            current = None
        elif name == "END":
            depth -= 1
        elif depth == 0:
            if name == "EXDATE":
                exdates.append((parameters, value))
            elif name not in current:
                current[name] = (parameters, value)
    return events


def _event(
    props: dict[str, tuple[dict[str, str], str]], exdates: list[tuple[dict[str, str], str]], zone: tzinfo
) -> IcsEvent | None:
    if "DTSTART" not in props:
        return None
    status = props.get("STATUS", ({}, ""))[1].strip().upper()
    if status == "CANCELLED":
        return None
    try:
        start, all_day = parse_value(props["DTSTART"][1], props["DTSTART"][0], zone)
        end: datetime | None = None
        if "DTEND" in props:
            end = parse_value(props["DTEND"][1], props["DTEND"][0], zone)[0]
        elif "DURATION" in props and (duration := parse_duration(props["DURATION"][1])) is not None:
            end = start + duration
        elif all_day:
            end = start + timedelta(days=1)
        skipped: list[datetime] = []
        for parameters, value in exdates:
            for part in value.split(","):
                if part.strip():
                    skipped.append(parse_value(part, parameters, start.tzinfo or zone)[0])
    except ValueError:
        return None
    title = unescape(props.get("SUMMARY", ({}, ""))[1]) or "Termin"
    uid = props.get("UID", ({}, ""))[1].strip() or f"{start.isoformat()}-{title}"
    rrule = props.get("RRULE", ({}, ""))[1].strip() or None
    return IcsEvent(uid, title, start, end, all_day, rrule, tuple(skipped))


def _rule(rrule: str) -> dict[str, str]:
    parts = {}
    for part in rrule.split(";"):
        key, _, value = part.partition("=")
        if key:
            parts[key.strip().upper()] = value.strip().upper()
    return parts


def _add_months(moment: datetime, months: int) -> datetime | None:
    month_index = moment.month - 1 + months
    year, month = moment.year + month_index // 12, month_index % 12 + 1
    try:
        return moment.replace(year=year, month=month)
    except ValueError:
        return None  # For example the 31st in a shorter month: RFC 5545 skips it.


def occurrences(
    start: datetime,
    rrule: str | None,
    window_start: datetime,
    window_end: datetime,
    *,
    duration: timedelta = timedelta(0),
    exdates: tuple[datetime, ...] = (),
) -> list[datetime]:
    """Start times of an event that overlap ``[window_start, window_end)``.

    Recurrences are computed in the event's own wall-clock time, so a weekly 09:00 meeting
    stays at 09:00 across daylight saving changes.
    """

    def overlaps(moment: datetime) -> bool:
        if duration > timedelta(0):
            return moment < window_end and moment + duration > window_start
        return window_start <= moment < window_end

    if not rrule:
        return [start] if overlaps(start) else []
    rule = _rule(rrule)
    frequency = rule.get("FREQ", "")
    if frequency not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
        return [start] if overlaps(start) else []
    interval = max(1, int(rule["INTERVAL"]) if rule.get("INTERVAL", "").isdigit() else 1)
    count = int(rule["COUNT"]) if rule.get("COUNT", "").isdigit() else None
    until: datetime | None = None
    if rule.get("UNTIL"):
        try:
            until = parse_value(rule["UNTIL"], {}, start.tzinfo or UTC)[0]
            if len(rule["UNTIL"].strip()) == 8:
                until += timedelta(days=1) - timedelta(seconds=1)
        except ValueError:
            until = None
    zone = start.tzinfo
    wall = start.replace(tzinfo=None)
    weekdays = sorted(
        {_WEEKDAYS[d[-2:]] for d in rule.get("BYDAY", "").split(",") if d[-2:] in _WEEKDAYS}
    ) or [wall.weekday()]
    skipped = {moment.astimezone(UTC) for moment in exdates}
    # Without a count, periods long before the window can be skipped.
    period = 0
    if count is None and frequency in ("DAILY", "WEEKLY"):
        unit = interval if frequency == "DAILY" else 7 * interval
        behind = (window_start.replace(tzinfo=None) - duration - wall).days
        period = max(0, behind // unit - 1)

    def period_starts(index: int) -> list[datetime]:
        if frequency == "DAILY":
            return [wall + timedelta(days=index * interval)]
        if frequency == "WEEKLY":
            week = wall - timedelta(days=wall.weekday()) + timedelta(weeks=index * interval)
            return [week + timedelta(days=day) for day in weekdays if week + timedelta(days=day) >= wall]
        months = index * interval * (12 if frequency == "YEARLY" else 1)
        moment = _add_months(wall, months)
        return [moment] if moment is not None else []

    found: list[datetime] = []
    produced = 0
    for index in range(period, period + MAX_OCCURRENCES):
        for candidate in period_starts(index):
            moment = candidate.replace(tzinfo=zone)
            produced += 1
            if (until is not None and moment > until) or (count is not None and produced > count):
                return found
            if moment >= window_end:
                return found
            if moment.astimezone(UTC) not in skipped and overlaps(moment):
                found.append(moment)
    return found


def day_window(day: date, zone: tzinfo) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(), zone)
    return start, datetime.combine(day + timedelta(days=1), time(), zone)
