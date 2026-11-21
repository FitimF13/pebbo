"""Calendars, ICS subscriptions, the morning briefing and presence."""

import asyncio
import threading
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pebbo import clock
from pebbo.app import create_app
from pebbo.briefing import briefing_hint, briefing_text
from pebbo.calendars.ics import day_window, occurrences, parse_ics
from pebbo.calendars.storage import calendar_book
from pebbo.calendars.sync import CalendarAddressError, CalendarSync, check_address, sync_source
from pebbo.presence import PresenceEvent, PresenceService, presence_for
from pebbo.routines.storage import routine_book
from pebbo.store import Person, Store
from pebbo.tools import builtin_tools
from pebbo.tools.registry import ToolContext, ToolResult
from pebbo.voice.assistant import context_message
from pebbo.voice.session import ConversationState

ZONE = clock.timezone()

ICS = "\r\n".join(
    [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "BEGIN:VEVENT",
        "UID:dentist@example.test",
        "DTSTART;TZID=Europe/Zurich:20261123T090000",
        "DTEND;TZID=Europe/Zurich:20261123T093000",
        "SUMMARY:Zahnarzt\\, Kontrolle",
        "BEGIN:VALARM",
        "TRIGGER:-PT15M",
        "SUMMARY:Alarm, nicht der Termin",
        "END:VALARM",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "UID:standup@example.test",
        "DTSTART:20261102T080000Z",
        "DURATION:PT15M",
        "RRULE:FREQ=WEEKLY;BYDAY=MO,WE;UNTIL=20261231T235959Z",
        "EXDATE:20261125T080000Z",
        "SUMMARY:Standup mit einem sehr langen Titel, der auf die nächste Zeile ",
        " umbricht",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "UID:holiday@example.test",
        "DTSTART;VALUE=DATE:20261124",
        "DTEND;VALUE=DATE:20261126",
        "SUMMARY:Ferien",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "UID:cancelled@example.test",
        "DTSTART:20261123T120000",
        "STATUS:CANCELLED",
        "SUMMARY:Abgesagt",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "UID:birthday@example.test",
        "DTSTART;VALUE=DATE:20200310",
        "RRULE:FREQ=YEARLY",
        "SUMMARY:Geburtstag Leon",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
)


@pytest.fixture
def store() -> Store:
    return Store(":memory:")


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZONE)


def run_tool(store: Store, person: Person | None, tool: str, **arguments: Any) -> ToolResult:
    return asyncio.run(builtin_tools().call(tool, arguments, ToolContext(store, person, None)))


def test_ics_events_are_parsed_with_time_zones_recurrence_and_exceptions() -> None:
    events = {event.uid.split("@")[0]: event for event in parse_ics(ICS, ZONE)}

    assert set(events) == {"dentist", "standup", "holiday", "birthday"}
    dentist = events["dentist"]
    assert dentist.title == "Zahnarzt, Kontrolle"
    assert dentist.start == datetime(2026, 11, 23, 9, tzinfo=ZONE)
    assert dentist.end == datetime(2026, 11, 23, 9, 30, tzinfo=ZONE)
    assert events["standup"].title.endswith("nächste Zeile umbricht")
    assert events["holiday"].all_day and events["holiday"].end == datetime(2026, 11, 26, tzinfo=ZONE)

    standup = events["standup"]
    week = (datetime(2026, 11, 23, tzinfo=ZONE), datetime(2026, 11, 30, tzinfo=ZONE))
    found = occurrences(
        standup.start, standup.rrule, *week, duration=timedelta(minutes=15), exdates=standup.exdates
    )
    assert [(m.weekday(), m.astimezone(ZONE).hour) for m in found] == [(0, 9)], "Wednesday is excluded"
    birthday = events["birthday"]
    window = day_window(date(2027, 3, 10), ZONE)
    assert len(occurrences(birthday.start, birthday.rrule, *window, duration=timedelta(days=1))) == 1


def test_recurrence_keeps_wall_clock_time_and_respects_count() -> None:
    start = datetime(2026, 3, 23, 9, tzinfo=ZONE)  # before the change to summer time

    weekly = occurrences(start, "FREQ=WEEKLY;COUNT=3", start, start + timedelta(days=60))
    daily = occurrences(start, "FREQ=DAILY;INTERVAL=2", start + timedelta(days=3), start + timedelta(days=8))
    monthly = occurrences(
        datetime(2026, 1, 31, 9, tzinfo=ZONE), "FREQ=MONTHLY", start, datetime(2026, 6, 1, tzinfo=ZONE)
    )

    assert [m.strftime("%m-%d %H:%M") for m in weekly] == ["03-23 09:00", "03-30 09:00", "04-06 09:00"]
    assert [m.day for m in daily] == [27, 29], "the end of the window is exclusive"
    assert [m.strftime("%m-%d") for m in monthly] == ["03-31", "05-31"], "months without the 31st are skipped"


class _Feed(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = ICS.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/calendar")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: Any) -> None:
        return


@pytest.fixture
def feed() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Feed)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/family.ics"
    server.shutdown()


def test_a_subscription_on_the_home_network_is_synced(store: Store, feed: str) -> None:
    alex = store.add_person("Alex", "owner")
    url, host, external = check_address(feed)
    book = calendar_book(store)
    source = book.add_source(alex.id, "Familie", url, host, external=external)

    assert not external
    assert sync_source(store, source) == 4
    assert sync_source(store, source) == 4, "a sync replaces the events instead of adding them again"
    day = book.occurrences(*day_window(date(2026, 11, 23), ZONE), (alex.id,))
    assert sorted(o.title for o in day) == [
        "Standup mit einem sehr langen Titel, der auf die nächste Zeile umbricht",
        "Zahnarzt, Kontrolle",
    ]
    assert book.source(source.id).last_synced_at is not None  # type: ignore[union-attr]


def test_external_calendar_hosts_are_off_until_the_owner_allows_them(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    allowed: list[set[str]] = []
    monkeypatch.setattr("pebbo.calendars.sync.netguard.allow", lambda hosts: allowed.append(set(hosts)))
    monkeypatch.setattr("pebbo.calendars.sync.netguard.revoke", lambda hosts: allowed.append({"-", *hosts}))
    book = calendar_book(store)
    url, host, external = check_address("webcal://calendar.example.test/family.ics")
    assert (url, host, external) == (
        "https://calendar.example.test/family.ics",
        "calendar.example.test",
        True,
    )
    with pytest.raises(CalendarAddressError):
        check_address("http://calendar.example.test/family.ics")
    with pytest.raises(CalendarAddressError):
        check_address("https://user:secret@calendar.example.test/family.ics")
    assert check_address("http://nas.local/cal.ics")[2] is False
    assert check_address("http://192.168.1.20/cal.ics")[2] is False
    source = book.add_source(None, "Schule", url, host, external=True)
    fetched: list[str] = []

    def fetch(address: str) -> str:
        fetched.append(address)
        return ICS

    with pytest.raises(PermissionError):
        sync_source(store, source, fetch)
    assert fetched == []

    book.allow_external(source.id, True)
    sync = CalendarSync(store, fetch)
    assert asyncio.run(sync.sync(source.id)) == 4
    assert fetched == [url] and {"calendar.example.test"} in allowed
    book.allow_external(source.id, False)
    sync.refresh_guard()
    assert {"-", "calendar.example.test"} in allowed, "withdrawing the permission revokes the host"


def test_calendar_tools_add_list_and_delete(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    alex = store.add_person("Alex", "owner")
    sara = store.add_person("Sara", "adult")
    tomorrow = clock.now().date() + timedelta(days=1)

    added = run_tool(store, alex, "add_event", title="Zahnarzt", start=f"{tomorrow}T09:00")
    assert added.say == "Eingetragen: Zahnarzt, morgen um 09:00."
    assert run_tool(store, alex, "add_event", title="Zahnarzt", start=f"{tomorrow}T09:00").outcome == "known"
    run_tool(store, alex, "add_event", title="Grillfest", start=str(tomorrow), household=True)
    run_tool(store, sara, "add_event", title="Yoga", start=f"{tomorrow}T18:00")

    listed = run_tool(store, alex, "list_events", day="morgen")
    assert listed.say == "Morgen hast du 2 Termine: ganztägig Grillfest und um 09:00 Zahnarzt."
    assert "Yoga" not in listed.say
    assert run_tool(store, None, "list_events", day="morgen").outcome == "denied"
    assert run_tool(store, alex, "delete_event", what="Zahnarzt").say == "Termin gelöscht: Zahnarzt."
    assert run_tool(store, alex, "list_events", day="heute").say == "Heute hast du keine Termine."


def test_briefing_names_todays_events_reminders_and_routines(store: Store) -> None:
    alex = store.add_person("Alex", "owner")
    today = date(2026, 11, 23)
    book = calendar_book(store)
    book.add_event(alex.id, "Zahnarzt", at(today, 9), at(today, 9, 30))
    book.add_event(None, "Ferien", at(today, 0), at(today + timedelta(days=1), 0), all_day=True)
    book.add_event(alex.id, "Morgen", at(today + timedelta(days=1), 9))
    store.add_reminder(alex.id, "Paket mitnehmen", at(today, 12).timestamp())
    store.add_reminder(alex.id, "Nächste Woche", at(today + timedelta(days=7), 12).timestamp())
    routine_book(store).add(
        alex.id,
        "Lüften",
        "",
        {"type": "time", "at": "10:00", "weekdays": []},
        [],
        [{"type": "say", "text": "Lüften!"}],
        cooldown_minutes=0,
        daily_limit=1,
        status="active",
    )

    text = briefing_text(store, alex, at(today, 7, 30))

    assert text == (
        "Guten Morgen, Alex! Heute hast du 2 Termine: ganztägig Ferien und um 09:00 Zahnarzt. "
        "Erinnerungen: um 12:00 Paket mitnehmen. Routinen: um 10:00 «Lüften»."
    )
    empty = store.add_person("Sara", "adult")
    assert briefing_text(store, empty, at(today + timedelta(days=3), 13)) == (
        "Hallo, Sara! Heute stehen keine Termine und keine Erinnerungen an."
    )


def test_briefing_is_offered_once_a_day_after_five_and_never_to_guests(store: Store) -> None:
    alex = store.add_person("Alex", "owner")
    today = date(2026, 11, 23)
    calendar_book(store).add_event(alex.id, "Zahnarzt", at(today, 9))
    calendar_book(store).add_event(alex.id, "Training", at(today + timedelta(days=1), 9))
    state = ConversationState(store, recognizer=None)

    assert briefing_hint(store, alex, at(today, 4, 30)) == ""
    guest = context_message(state, at(today, 7))
    assert "Zahnarzt" not in guest and "Überblick" not in guest
    state.person = alex
    first = context_message(state, at(today, 7))
    assert "Termine heute:\n- um 09:00 Zahnarzt" in first and "zum ersten Mal" in first
    assert "Training" not in first
    again = context_message(state, at(today, 7, 5))
    assert "Zahnarzt" in again and "zum ersten Mal" not in again
    assert "zum ersten Mal" in context_message(state, at(today + timedelta(days=1), 8))


def test_daily_briefing_tool(store: Store) -> None:
    alex = store.add_person("Alex", "owner")

    assert run_tool(store, alex, "daily_briefing").say.startswith(("Guten Morgen, Alex!", "Hallo, Alex!"))
    assert run_tool(store, None, "daily_briefing").outcome == "denied"


def test_control_api_manages_events_and_subscriptions(store: Store) -> None:
    alex = store.add_person("Alex", "owner")
    client = TestClient(create_app(store=store))
    today = clock.now().date()

    event = client.post(
        "/api/control/calendar/events",
        json={"person_id": alex.id, "title": "Zahnarzt", "start": f"{today}T23:00"},
    ).json()
    assert event["title"] == "Zahnarzt" and not event["all_day"]
    assert [e["title"] for e in client.get("/api/control/calendar/events").json()] == ["Zahnarzt"]
    assert (
        client.post(
            "/api/control/calendar/events", json={"person_id": 99, "title": "x", "start": str(today)}
        ).status_code
        == 404
    )
    assert client.delete(f"/api/control/calendar/events/{event['event_id']}").status_code == 204

    bad = client.post(
        "/api/control/calendar/sources", json={"person_id": None, "url": "ftp://example.test/x"}
    )
    assert bad.status_code == 400
    source = client.post(
        "/api/control/calendar/sources",
        json={"person_id": None, "name": "Schule", "url": "https://cal.example.test/s.ics"},
    ).json()
    assert source["external"] and not source["allow_external"]
    refused = client.post(f"/api/control/calendar/sources/{source['id']}/sync")
    assert refused.status_code == 400 and "cal.example.test" in refused.json()["detail"]
    assert client.delete(f"/api/control/calendar/sources/{source['id']}").status_code == 204
    assert client.get("/api/control/calendar/sources").json() == []


def test_presence_reports_arrivals_and_departures(store: Store) -> None:
    presence = PresenceService(away_after=600)
    events: list[PresenceEvent] = []
    presence.subscribe(events.append)

    presence.heard(1, 1000)
    presence.heard(1, 1100)
    assert presence.status(1) == "near" and presence.status(2) == "unknown"
    assert presence.update(1500) == []
    assert [e.kind for e in presence.update(1700)] == ["leave"]
    assert presence.status(1) == "away" and presence.near_people() == set()
    presence.heard(1, 1800)
    assert [(e.kind, e.person_id, e.at) for e in events] == [
        ("arrive", 1, 1000),
        ("leave", 1, 1700),
        ("arrive", 1, 1800),
    ]


def test_speaker_identification_marks_the_person_near(store: Store) -> None:
    from pebbo.people.speaker import Identification

    alex = store.add_person("Alex", "owner")
    state = ConversationState(store, recognizer=None)
    import numpy as np

    state.apply(Identification(alex.id, 0.9, np.zeros(4, dtype=np.float32)))

    assert presence_for(store).is_near(alex.id)
