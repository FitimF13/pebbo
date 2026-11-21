"""Pebbo's local calendar and its read-only subscriptions, in tables of the instance database.

Every event belongs to a person or, with ``person_id`` ``None``, to the household. Events
from a subscription (an ICS address the owner entered) are replaced on every sync.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import weakref
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo

from pebbo import clock
from pebbo.calendars.ics import IcsEvent, occurrences
from pebbo.store import Store

SCHEMA = """
CREATE TABLE IF NOT EXISTS calendar_sources (
    id INTEGER PRIMARY KEY,
    person_id INTEGER REFERENCES people(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    host TEXT NOT NULL,
    external INTEGER NOT NULL,
    allow_external INTEGER NOT NULL DEFAULT 0,
    last_synced_at REAL,
    last_error TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS calendar_events (
    id INTEGER PRIMARY KEY,
    person_id INTEGER REFERENCES people(id) ON DELETE CASCADE,
    source_id INTEGER REFERENCES calendar_sources(id) ON DELETE CASCADE,
    uid TEXT NOT NULL,
    title TEXT NOT NULL,
    starts_at REAL NOT NULL,
    ends_at REAL,
    all_day INTEGER NOT NULL DEFAULT 0,
    time_zone TEXT,
    rrule TEXT,
    exdates TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS calendar_events_start ON calendar_events (starts_at);
"""


@dataclass(frozen=True)
class CalendarEvent:
    id: int
    person_id: int | None
    source_id: int | None
    uid: str
    title: str
    starts_at: float
    ends_at: float | None
    all_day: bool
    time_zone: str | None
    rrule: str | None
    exdates: tuple[float, ...]


@dataclass(frozen=True)
class Occurrence:
    """One appointment on the calendar: an event, or one repetition of a recurring event."""

    event: CalendarEvent
    start: datetime
    end: datetime | None

    @property
    def all_day(self) -> bool:
        return self.event.all_day

    @property
    def title(self) -> str:
        return self.event.title


@dataclass(frozen=True)
class CalendarSource:
    id: int
    person_id: int | None
    name: str
    url: str
    host: str
    # Whether the host is outside the home network. Such hosts need the owner's permission.
    external: bool
    allow_external: bool
    last_synced_at: float | None
    last_error: str | None


class CalendarBook:
    """Thread-safe access to the calendar tables."""

    def __init__(self, store: Store) -> None:
        self._db, self._lock = store.extension(SCHEMA)

    # Events ---------------------------------------------------------------

    def add_event(
        self,
        person_id: int | None,
        title: str,
        start: datetime,
        end: datetime | None = None,
        *,
        all_day: bool = False,
        uid: str = "",
        rrule: str | None = None,
        exdates: tuple[datetime, ...] = (),
        source_id: int | None = None,
    ) -> CalendarEvent:
        title = " ".join(title.split())
        if not title:
            raise ValueError("An event needs a title.")
        zone = getattr(start.tzinfo, "key", None)
        with self._lock, self._db:
            cursor = self._db.execute(
                "INSERT INTO calendar_events (person_id, source_id, uid, title, starts_at, ends_at, all_day, "
                "time_zone, rrule, exdates, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    person_id,
                    source_id,
                    uid or f"pebbo-{time.time_ns()}",
                    title,
                    start.timestamp(),
                    end.timestamp() if end else None,
                    int(all_day),
                    zone,
                    rrule,
                    json.dumps([moment.timestamp() for moment in exdates]),
                    time.time(),
                ),
            )
        event = self.event(int(cursor.lastrowid or 0))
        if event is None:
            raise RuntimeError("The new event could not be read back.")
        return event

    def event(self, event_id: int) -> CalendarEvent | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM calendar_events WHERE id = ?", (event_id,)).fetchone()
        return _event(row) if row else None

    def delete_event(self, event_id: int) -> bool:
        with self._lock, self._db:
            return self._db.execute("DELETE FROM calendar_events WHERE id = ?", (event_id,)).rowcount > 0

    def events(self, person_ids: tuple[int | None, ...] | None = None) -> list[CalendarEvent]:
        """All events, or those of some people (``None`` in the tuple means the household)."""
        query = "SELECT * FROM calendar_events"
        values: list[object] = []
        if person_ids is not None:
            people = [pid for pid in person_ids if pid is not None]
            clauses = ["person_id IS NULL"] if None in person_ids else []
            if people:
                clauses.append(f"person_id IN ({', '.join('?' for _ in people)})")
                values.extend(people)
            query += " WHERE " + (" OR ".join(clauses) or "0")
        with self._lock:
            rows = self._db.execute(query + " ORDER BY starts_at", values).fetchall()
        return [_event(row) for row in rows]

    def occurrences(
        self, start: datetime, end: datetime, person_ids: tuple[int | None, ...] | None = None
    ) -> list[Occurrence]:
        """Appointments overlapping ``[start, end)``, in order."""
        zone = start.tzinfo or clock.timezone()
        found: list[Occurrence] = []
        for event in self.events(person_ids):
            event_zone = _zone(event.time_zone)
            first = datetime.fromtimestamp(event.starts_at, event_zone)
            duration = timedelta(seconds=(event.ends_at - event.starts_at)) if event.ends_at else timedelta(0)
            skipped = tuple(datetime.fromtimestamp(stamp, event_zone) for stamp in event.exdates)
            for moment in occurrences(first, event.rrule, start, end, duration=duration, exdates=skipped):
                local = moment.astimezone(zone)
                found.append(Occurrence(event, local, local + duration if event.ends_at else None))
        return sorted(found, key=lambda o: (not o.all_day, o.start))

    def replace_source_events(self, source_id: int, person_id: int | None, events: list[IcsEvent]) -> int:
        """Swap the events of a subscription for freshly read ones."""
        rows = [
            (
                person_id,
                source_id,
                event.uid,
                event.title,
                event.start.timestamp(),
                event.end.timestamp() if event.end else None,
                int(event.all_day),
                getattr(event.start.tzinfo, "key", None),
                event.rrule,
                json.dumps([moment.timestamp() for moment in event.exdates]),
                time.time(),
            )
            for event in events
        ]
        with self._lock, self._db:
            self._db.execute("DELETE FROM calendar_events WHERE source_id = ?", (source_id,))
            self._db.executemany(
                "INSERT INTO calendar_events (person_id, source_id, uid, title, starts_at, ends_at, all_day, "
                "time_zone, rrule, exdates, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        return len(rows)

    # Subscriptions ----------------------------------------------------------

    def add_source(
        self, person_id: int | None, name: str, url: str, host: str, *, external: bool
    ) -> CalendarSource:
        with self._lock, self._db:
            cursor = self._db.execute(
                "INSERT INTO calendar_sources (person_id, name, url, host, external, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (person_id, name.strip() or host, url, host, int(external), time.time()),
            )
        source = self.source(int(cursor.lastrowid or 0))
        if source is None:
            raise RuntimeError("The new calendar source could not be read back.")
        return source

    def source(self, source_id: int) -> CalendarSource | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM calendar_sources WHERE id = ?", (source_id,)).fetchone()
        return _source(row) if row else None

    def sources(self) -> list[CalendarSource]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM calendar_sources ORDER BY id").fetchall()
        return [_source(row) for row in rows]

    def allow_external(self, source_id: int, allowed: bool) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE calendar_sources SET allow_external = ? WHERE id = ?", (int(allowed), source_id)
            )

    def synced(self, source_id: int, error: str | None) -> None:
        with self._lock, self._db:
            if error is None:
                self._db.execute(
                    "UPDATE calendar_sources SET last_synced_at = ?, last_error = NULL WHERE id = ?",
                    (time.time(), source_id),
                )
            else:
                self._db.execute(
                    "UPDATE calendar_sources SET last_error = ? WHERE id = ?", (error, source_id)
                )

    def delete_source(self, source_id: int) -> bool:
        with self._lock, self._db:
            return self._db.execute("DELETE FROM calendar_sources WHERE id = ?", (source_id,)).rowcount > 0


def _zone(name: str | None) -> tzinfo:
    if name:
        try:
            return ZoneInfo(name)
        except (ValueError, KeyError):
            pass
    return clock.timezone()


def _event(row: sqlite3.Row) -> CalendarEvent:
    return CalendarEvent(
        id=row["id"],
        person_id=row["person_id"],
        source_id=row["source_id"],
        uid=row["uid"],
        title=row["title"],
        starts_at=row["starts_at"],
        ends_at=row["ends_at"],
        all_day=bool(row["all_day"]),
        time_zone=row["time_zone"],
        rrule=row["rrule"],
        exdates=tuple(json.loads(row["exdates"] or "[]")),
    )


def _source(row: sqlite3.Row) -> CalendarSource:
    return CalendarSource(
        id=row["id"],
        person_id=row["person_id"],
        name=row["name"],
        url=row["url"],
        host=row["host"],
        external=bool(row["external"]),
        allow_external=bool(row["allow_external"]),
        last_synced_at=row["last_synced_at"],
        last_error=row["last_error"],
    )


_books: weakref.WeakKeyDictionary[Store, CalendarBook] = weakref.WeakKeyDictionary()
_books_lock = threading.Lock()


def calendar_book(store: Store) -> CalendarBook:
    """The calendar tables of this database, created on first use."""
    with _books_lock:
        book = _books.get(store)
        if book is None:
            book = _books[store] = CalendarBook(store)
        return book


def spoken_occurrence(occurrence: Occurrence) -> str:
    """An appointment as Pebbo says it, for example "um 09:00 Zahnarzt" or "ganztägig Ferien"."""
    if occurrence.all_day:
        return f"ganztägig {occurrence.title}"
    return f"um {occurrence.start.strftime('%H:%M')} {occurrence.title}"
