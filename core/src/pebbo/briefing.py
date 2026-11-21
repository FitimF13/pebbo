"""The morning briefing and the day's appointments in Pebbo's context.

The first time Pebbo recognises a person on a day (from 05:00), its context says so, and
Pebbo offers a short overview of the day in its own words. If the person wants it, the
action agent picks the ``daily_briefing`` tool, which says the day's appointments,
reminders and routines in a few sentences. There are no trigger words: the model decides
from the conversation. Guests never get any of this.
"""

from __future__ import annotations

import threading
import weakref
from datetime import datetime, time
from typing import Any

from pebbo import clock
from pebbo.calendars.storage import spoken_occurrence
from pebbo.calendars.tools import appointments_sentence, day_occurrences
from pebbo.routines.engine import scheduled_today
from pebbo.routines.storage import routine_book
from pebbo.store import Person, Store
from pebbo.tools.registry import Tool, ToolContext, ToolRegistry, ToolResult, speaker

# Before this, a first "hello" is still the night and gets no briefing offer.
MORNING = time(5, 0)
_MAX_ITEMS = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS briefing_offers (
    person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    PRIMARY KEY (person_id, day)
);
"""


class _Offers:
    def __init__(self, store: Store) -> None:
        self._db, self._lock = store.extension(SCHEMA)

    def first_today(self, person_id: int, day: str) -> bool:
        """Record that the person was greeted today. True only the first time."""
        with self._lock, self._db:
            cursor = self._db.execute(
                "INSERT OR IGNORE INTO briefing_offers (person_id, day) VALUES (?, ?)", (person_id, day)
            )
            self._db.execute("DELETE FROM briefing_offers WHERE day < date(?, '-7 days')", (day,))
        return cursor.rowcount > 0


_offers: weakref.WeakKeyDictionary[Store, _Offers] = weakref.WeakKeyDictionary()
_offers_lock = threading.Lock()


def _offers_for(store: Store) -> _Offers:
    with _offers_lock:
        offers = _offers.get(store)
        if offers is None:
            offers = _offers[store] = _Offers(store)
        return offers


def today_reminders(store: Store, person: Person, reference: datetime) -> list[tuple[datetime, str]]:
    end = datetime.combine(reference.date(), time.max, reference.tzinfo).timestamp()
    zone = reference.tzinfo or clock.timezone()
    return [
        (datetime.fromtimestamp(r.due_at, zone), r.text)
        for r in store.reminders(person.id)
        if r.due_at <= end
    ]


def today_routines(store: Store, person: Person, reference: datetime) -> list[tuple[datetime, str]]:
    """The person's active routines that still run today at a fixed time."""
    found = []
    for routine in routine_book(store).routines(person.id, "active"):
        moment = scheduled_today(routine, reference)
        if moment is not None and moment >= reference:
            found.append((moment, routine.name))
    return sorted(found)


def briefing_text(store: Store, person: Person, reference: datetime | None = None) -> str:
    """The day in a few spoken sentences."""
    reference = reference or clock.now()
    greeting = "Guten Morgen" if reference.hour < 11 else "Hallo"
    events = day_occurrences(store, person, reference.date())
    reminders = today_reminders(store, person, reference)
    routines = today_routines(store, person, reference)
    parts = [f"{greeting}, {person.name}!"]
    if not (events or reminders or routines):
        parts.append("Heute stehen keine Termine und keine Erinnerungen an.")
        return " ".join(parts)
    parts.append(appointments_sentence(events[:_MAX_ITEMS], "heute"))
    if reminders:
        items = [f"um {moment.strftime('%H:%M')} {text}" for moment, text in reminders[:_MAX_ITEMS]]
        parts.append(f"Erinnerungen: {_join(items)}.")
    if routines:
        items = [f"um {moment.strftime('%H:%M')} «{name}»" for moment, name in routines[:_MAX_ITEMS]]
        parts.append(f"Routinen: {_join(items)}.")
    return " ".join(parts)


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " und " + items[-1]


def briefing_hint(store: Store, person: Person, reference: datetime | None = None) -> str:
    """A hint for the conversation model the first time it hears the person on a day."""
    reference = reference or clock.now()
    if reference.timetz().replace(tzinfo=None) < MORNING:
        return ""
    if not _offers_for(store).first_today(person.id, reference.date().isoformat()):
        return ""
    has_day = (
        day_occurrences(store, person, reference.date())
        or today_reminders(store, person, reference)
        or today_routines(store, person, reference)
    )
    if not has_day:
        return ""
    return (
        f"Du hörst {person.name} heute zum ersten Mal. Biete am Ende deiner Antwort kurz an, einen Überblick "
        "über den Tag zu geben, ohne ihn schon zu geben. Möchte die Person ihn, sagt das System ihn selbst, "
        "dann antwortest du nur kurz, zum Beispiel 'Gern, hier kommt dein Tag.'"
    )


def personal_lines(store: Store, person: Person, reference: datetime | None = None) -> list[str]:
    """Today's appointments and the briefing hint, for the context of a recognised person."""
    reference = reference or clock.now()
    lines: list[str] = []
    events = day_occurrences(store, person, reference.date())
    if events:
        lines.append("Termine heute:")
        lines += [f"- {spoken_occurrence(event)}" for event in events[:10]]
    hint = briefing_hint(store, person, reference)
    if hint:
        lines.append(hint)
    return lines


async def daily_briefing(context: ToolContext, _arguments: dict[str, Any]) -> ToolResult:
    person = speaker(context)
    return ToolResult(briefing_text(context.store, person), outcome="briefed")


def register_briefing_tools(registry: ToolRegistry) -> None:
    registry.register(
        Tool(
            name="daily_briefing",
            description=(
                "Gibt der Person einen kurzen Überblick über ihren Tag: Termine, Erinnerungen und Routinen. "
                "Wenn sie den Überblick möchte, zum Beispiel nachdem Pebbo ihn angeboten hat, oder fragt, "
                "was heute ansteht."
            ),
            parameters={"type": "object", "properties": {}},
            run=daily_briefing,
        )
    )
