"""Tools for appointments in Pebbo's local calendar."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from pebbo import clock
from pebbo.calendars.ics import day_window
from pebbo.calendars.storage import Occurrence, calendar_book, spoken_occurrence
from pebbo.store import Person, Store
from pebbo.tools.memory import overlap, similarity
from pebbo.tools.registry import Tool, ToolContext, ToolRegistry, ToolResult, speaker, text_argument

_RELATIVE_DAYS = {"heute": 0, "today": 0, "morgen": 1, "tomorrow": 1, "übermorgen": 2, "uebermorgen": 2}


def parse_day(value: str, reference: datetime | None = None) -> date:
    """A day from "heute", "morgen", "übermorgen", a weekday name or ``JJJJ-MM-TT``."""
    reference = reference or clock.now()
    word = value.strip().lower()
    if word in _RELATIVE_DAYS or not word:
        return reference.date() + timedelta(days=_RELATIVE_DAYS.get(word, 0))
    for index, name in enumerate(clock.WEEKDAYS):
        if word.startswith(name.lower()):
            ahead = (index - reference.weekday()) % 7
            return reference.date() + timedelta(days=ahead)
    try:
        return date.fromisoformat(word[:10])
    except ValueError as error:
        raise ValueError("Den Tag habe ich nicht verstanden.") from error


def spoken_day(day: date, reference: datetime | None = None) -> str:
    reference = reference or clock.now()
    days = (day - reference.date()).days
    if days in (0, 1, 2):
        return ("heute", "morgen", "übermorgen")[days]
    return f"am {clock.WEEKDAYS[day.weekday()]}, {day.day}. {clock.MONTHS[day.month - 1]}"


def day_occurrences(store: Store, person: Person, day: date) -> list[Occurrence]:
    """The person's and the household's appointments on a day."""
    start, end = day_window(day, clock.timezone())
    return calendar_book(store).occurrences(start, end, (person.id, None))


def spoken_list(items: list[Occurrence]) -> str:
    texts = [spoken_occurrence(item) for item in items]
    return texts[0] if len(texts) == 1 else ", ".join(texts[:-1]) + " und " + texts[-1]


def appointments_sentence(items: list[Occurrence], day_text: str) -> str:
    if not items:
        return f"{day_text[:1].upper() + day_text[1:]} hast du keine Termine."
    count = "einen Termin" if len(items) == 1 else f"{len(items)} Termine"
    return f"{day_text[:1].upper() + day_text[1:]} hast du {count}: {spoken_list(items)}."


def parse_start(value: str, reference: datetime | None = None) -> tuple[datetime, bool]:
    """A start as ``JJJJ-MM-TTTHH:MM`` (with time) or ``JJJJ-MM-TT`` (whole day)."""
    reference = reference or clock.now()
    text = value.strip()
    try:
        if len(text) <= 10:
            return datetime.combine(date.fromisoformat(text), time(), reference.tzinfo), True
        moment = datetime.fromisoformat(text)
    except ValueError as error:
        raise ValueError("Die Zeit muss im Format JJJJ-MM-TTTHH:MM angegeben werden.") from error
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=reference.tzinfo)
    return moment, False


async def add_event(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    person = speaker(context)
    title = text_argument(arguments, "title")
    if not title:
        return ToolResult(ok=False, outcome="empty")
    reference = clock.now()
    try:
        start, all_day = parse_start(text_argument(arguments, "start"), reference)
        end = parse_start(text_argument(arguments, "end"), reference)[0] if arguments.get("end") else None
    except ValueError as error:
        return ToolResult(f"Den Termin konnte ich nicht eintragen. {error}", ok=False, outcome="invalid")
    if start.date() < reference.date():
        return ToolResult("Dieser Tag liegt in der Vergangenheit.", ok=False, outcome="invalid")
    if all_day:
        end = start + timedelta(days=1)
    elif end is None or end <= start:
        end = start + timedelta(hours=1)
    household = arguments.get("household") is True
    book = calendar_book(context.store)
    owner = None if household else person.id
    same = [
        o
        for o in book.occurrences(start - timedelta(minutes=30), start + timedelta(minutes=30), (owner,))
        if similarity(o.title, title) >= 0.75
    ]
    if same:
        return ToolResult("Den Termin habe ich schon.", outcome="known")
    book.add_event(owner, title, start, end, all_day=all_day)
    when = spoken_day(start.date(), reference) + ("" if all_day else f" um {start.strftime('%H:%M')}")
    whose = " für alle" if household else ""
    return ToolResult(
        f"Eingetragen{whose}: {title}, {when}.",
        outcome="added",
        data={"title": title, "start": start.isoformat()},
    )


async def list_events(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    person = speaker(context)
    reference = clock.now()
    try:
        day = parse_day(text_argument(arguments, "day"), reference)
    except ValueError as error:
        return ToolResult(str(error), ok=False, outcome="invalid")
    items = day_occurrences(context.store, person, day)
    return ToolResult(appointments_sentence(items, spoken_day(day, reference)), outcome="listed")


async def delete_event(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    person = speaker(context)
    what = text_argument(arguments, "what")
    reference = clock.now()
    book = calendar_book(context.store)
    start = datetime.combine(reference.date(), time(), reference.tzinfo)
    items = book.occurrences(start, start + timedelta(days=60), (person.id, None))
    if arguments.get("day"):
        try:
            day = parse_day(text_argument(arguments, "day"), reference)
        except ValueError:
            day = None
        if day is not None:
            items = [item for item in items if item.start.date() == day] or items
    best = max(items, key=lambda o: (overlap(o.title, what), similarity(o.title, what)), default=None)
    if best is None or overlap(best.title, what) == 0:
        return ToolResult("Diesen Termin habe ich nicht gefunden.", ok=False, outcome="missing")
    if best.event.source_id is not None:
        return ToolResult(
            "Dieser Termin kommt aus einem abonnierten Kalender. Den kann ich nur lesen.",
            ok=False,
            outcome="read-only",
        )
    book.delete_event(best.event.id)
    return ToolResult(f"Termin gelöscht: {best.title}.", outcome="deleted", data={"title": best.title})


def register_calendar_tools(registry: ToolRegistry) -> None:
    registry.register(
        Tool(
            name="add_event",
            description=(
                "Trägt einen Termin in Pebbos Kalender ein, wenn die Person einen Termin eintragen möchte "
                "oder einen festen Termin nennt, den Pebbo sich merken soll. Für eine Erinnerung zu einer "
                "Zeit ist set_reminder da."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Worum es geht, z. B. 'Zahnarzt'"},
                    "start": {
                        "type": "string",
                        "description": "Beginn lokal als JJJJ-MM-TTTHH:MM, für ganztägig nur JJJJ-MM-TT",
                    },
                    "end": {"type": "string", "description": "Ende als JJJJ-MM-TTTHH:MM, sonst leer"},
                    "household": {
                        "type": "boolean",
                        "description": "true, wenn der Termin für den ganzen Haushalt gilt",
                    },
                },
                "required": ["title", "start"],
            },
            run=add_event,
        )
    )
    registry.register(
        Tool(
            name="list_events",
            description=(
                "Sagt die Termine der Person an einem Tag, wenn sie nach ihren Terminen fragt, z. B. 'Was "
                "habe ich morgen?'."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "day": {
                        "type": "string",
                        "description": "'heute', 'morgen', ein Wochentag oder JJJJ-MM-TT",
                    }
                },
                "required": ["day"],
            },
            run=list_events,
        )
    )
    registry.register(
        Tool(
            name="delete_event",
            description=(
                "Löscht einen Termin aus Pebbos Kalender, wenn die Person ihn absagen oder löschen möchte."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "what": {"type": "string", "description": "Worum es beim Termin geht"},
                    "day": {"type": "string", "description": "Der Tag, falls genannt, sonst leer"},
                },
                "required": ["what"],
            },
            run=delete_event,
        )
    )
