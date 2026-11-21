"""Control centre API for the calendar: appointments and read-only ICS subscriptions."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from pebbo import clock
from pebbo.calendars.storage import CalendarSource, Occurrence, calendar_book
from pebbo.calendars.sync import CalendarAddressError, CalendarSync, check_address
from pebbo.store import Store


class OccurrenceOut(BaseModel):
    event_id: int
    person_id: int | None
    source_id: int | None
    title: str
    start: float
    end: float | None
    all_day: bool
    recurring: bool


class EventIn(BaseModel):
    person_id: int | None
    title: str = Field(min_length=1, max_length=200)
    # Local date (JJJJ-MM-TT) for a whole day, or local date and time (JJJJ-MM-TTTHH:MM).
    start: str = Field(min_length=10, max_length=25)
    end: str | None = Field(default=None, max_length=25)


class SourceOut(BaseModel):
    id: int
    person_id: int | None
    name: str
    # The full address is not returned: private calendar links contain a secret.
    host: str
    external: bool
    allow_external: bool
    last_synced_at: float | None
    last_error: str | None


class SourceIn(BaseModel):
    person_id: int | None
    name: str = Field(default="", max_length=60)
    url: str = Field(min_length=8, max_length=2000)


class SourcePatch(BaseModel):
    allow_external: bool


class SyncOut(BaseModel):
    events: int


def _occurrence(occurrence: Occurrence) -> OccurrenceOut:
    return OccurrenceOut(
        event_id=occurrence.event.id,
        person_id=occurrence.event.person_id,
        source_id=occurrence.event.source_id,
        title=occurrence.title,
        start=occurrence.start.timestamp(),
        end=occurrence.end.timestamp() if occurrence.end else None,
        all_day=occurrence.all_day,
        recurring=bool(occurrence.event.rrule),
    )


def _source(source: CalendarSource) -> SourceOut:
    return SourceOut(
        id=source.id,
        person_id=source.person_id,
        name=source.name,
        host=source.host,
        external=source.external,
        allow_external=source.allow_external,
        last_synced_at=source.last_synced_at,
        last_error=source.last_error,
    )


def _moment(value: str) -> tuple[datetime, bool]:
    zone = clock.timezone()
    try:
        if len(value.strip()) == 10:
            return datetime.combine(date.fromisoformat(value.strip()), time(), zone), True
        moment = datetime.fromisoformat(value.strip())
    except ValueError as error:
        raise HTTPException(400, "Datum oder Uhrzeit stimmen nicht.") from error
    return (moment if moment.tzinfo else moment.replace(tzinfo=zone)), False


def calendar_router(store: Store, sync: CalendarSync) -> APIRouter:
    router = APIRouter(prefix="/api/control/calendar")
    book = calendar_book(store)

    def require_person(person_id: int | None) -> None:
        if person_id is not None and store.person(person_id) is None:
            raise HTTPException(404, "Diese Person gibt es nicht.")

    def require_source(source_id: int) -> CalendarSource:
        source = book.source(source_id)
        if source is None:
            raise HTTPException(404, "Diesen Kalender gibt es nicht mehr.")
        return source

    @router.get("/events")
    def events(days: int = 14) -> list[OccurrenceOut]:
        start = datetime.combine(clock.now().date(), time(), clock.timezone())
        end = start + timedelta(days=max(1, min(days, 366)))
        return [_occurrence(o) for o in book.occurrences(start, end)]

    @router.post("/events", status_code=201)
    def add_event(body: EventIn) -> OccurrenceOut:
        require_person(body.person_id)
        start, all_day = _moment(body.start)
        end = _moment(body.end)[0] if body.end else None
        if all_day:
            end = start + timedelta(days=1)
        elif end is None or end <= start:
            end = start + timedelta(hours=1)
        event = book.add_event(body.person_id, body.title, start, end, all_day=all_day)
        found = book.occurrences(start, end + timedelta(seconds=1))
        match = next((o for o in found if o.event.id == event.id), None)
        if match is None:
            raise HTTPException(500, "Der Termin konnte nicht gelesen werden.")
        return _occurrence(match)

    @router.delete("/events/{event_id}", status_code=204)
    def delete_event(event_id: int) -> None:
        event = book.event(event_id)
        if event is None:
            raise HTTPException(404, "Diesen Termin gibt es nicht mehr.")
        if event.source_id is not None:
            raise HTTPException(400, "Termine aus einem abonnierten Kalender sind nur lesbar.")
        book.delete_event(event_id)

    @router.get("/sources")
    def sources() -> list[SourceOut]:
        return [_source(source) for source in book.sources()]

    @router.post("/sources", status_code=201)
    def add_source(body: SourceIn) -> SourceOut:
        require_person(body.person_id)
        try:
            url, host, external = check_address(body.url)
        except CalendarAddressError as error:
            raise HTTPException(400, str(error)) from error
        return _source(book.add_source(body.person_id, body.name, url, host, external=external))

    @router.patch("/sources/{source_id}")
    def update_source(source_id: int, body: SourcePatch) -> SourceOut:
        require_source(source_id)
        book.allow_external(source_id, body.allow_external)
        sync.refresh_guard()
        return _source(require_source(source_id))

    @router.post("/sources/{source_id}/sync")
    async def sync_source(source_id: int) -> SyncOut:
        source = require_source(source_id)
        if source.external and not source.allow_external:
            raise HTTPException(
                400, f"Der Host {source.host} liegt ausserhalb des Heimnetzes und ist nicht freigegeben."
            )
        try:
            return SyncOut(events=await sync.sync(source_id))
        except Exception as error:
            raise HTTPException(502, "Der Kalender konnte nicht gelesen werden.") from error

    @router.delete("/sources/{source_id}", status_code=204)
    def delete_source(source_id: int) -> None:
        if not book.delete_source(source_id):
            raise HTTPException(404, "Diesen Kalender gibt es nicht mehr.")
        sync.refresh_guard()

    return router
