"""Routines: teaching through tools, triggers, conditions, actions, limits and the run log."""

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pebbo import clock
from pebbo.app import create_app
from pebbo.presence import PresenceService
from pebbo.routines.engine import Firing, RoutineEngine, RoutineScheduler, StateChange
from pebbo.routines.model import RoutineError, describe, parse_weekdays
from pebbo.routines.storage import Routine, routine_book
from pebbo.routines.sun import sun_times
from pebbo.store import Person, Store
from pebbo.tools import builtin_tools
from pebbo.tools.registry import OWNER_ONLY, Tool, ToolContext, ToolRegistry, ToolResult

# A Monday.
MONDAY = datetime(2026, 11, 23, tzinfo=clock.timezone())


@pytest.fixture
def store() -> Store:
    return Store(":memory:")


class Speaker:
    def __init__(self) -> None:
        self.said: list[str] = []

    async def __call__(self, text: str) -> int:
        self.said.append(text)
        return 1


class FakeSource:
    """A device state source like a smart home hub."""

    def __init__(self, states: dict[str, str]) -> None:
        self.states = states
        self._listeners: list[Callable[[StateChange], None]] = []

    async def get_state(self, entity: str) -> str | None:
        return self.states.get(entity)

    def subscribe(self, listener: Callable[[StateChange], None]) -> None:
        self._listeners.append(listener)

    def change(self, entity: str, new: str) -> None:
        old = self.states.get(entity)
        self.states[entity] = new
        for listener in self._listeners:
            listener(StateChange(entity, old, new))


class Lights:
    """A fake smart home tool that switches lights off."""

    def __init__(self) -> None:
        self.calls: list[tuple[str | None, dict[str, Any]]] = []

    async def __call__(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        self.calls.append((context.person.name if context.person else None, arguments))
        return ToolResult("Ich habe drei Lichter ausgeschaltet.", outcome="switched")


def registry_with_lights(lights: Lights) -> ToolRegistry:
    registry = builtin_tools()
    registry.register(Tool("lights_off", "Schaltet Lichter aus.", {"type": "object"}, lights))
    return registry


def call(
    registry: ToolRegistry, store: Store, person: Person | None, tool: str, **arguments: Any
) -> ToolResult:
    return asyncio.run(registry.call(tool, arguments, ToolContext(store, person, None)))


def at(day: datetime, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return day.replace(hour=hour, minute=minute, second=second)


def active_routine(store: Store, person: Person, **overrides: Any) -> Routine:
    fields: dict[str, Any] = {
        "trigger": {"type": "time", "at": "07:00", "weekdays": []},
        "conditions": [],
        "actions": [{"type": "say", "text": "Guten Morgen"}],
        "cooldown_minutes": 0,
        "daily_limit": 5,
        "status": "active",
    }
    fields.update(overrides)
    book = routine_book(store)
    return book.add(
        person.id,
        fields.pop("name", "Test"),
        "",
        fields.pop("trigger"),
        fields.pop("conditions"),
        fields.pop("actions"),
        **fields,
    )


def test_teaching_creates_a_draft_that_needs_a_yes(store: Store) -> None:
    registry = builtin_tools()
    alex = store.add_person("Alex", "owner")

    draft = call(
        registry,
        store,
        alex,
        "teach_routine",
        name="Guten Morgen",
        trigger={"type": "time", "at": "7 Uhr", "weekdays": ["werktags"]},
        actions=[{"type": "say", "text": "Guten Morgen"}],
    )

    assert draft.outcome == "draft"
    assert draft.say == (
        "Ich habe verstanden: Montag bis Freitag um 07:00 sage ich «Guten Morgen». "
        "Soll ich die Routine so speichern?"
    )
    book = routine_book(store)
    assert [r.status for r in book.routines()] == ["draft"]

    changed = call(
        registry,
        store,
        alex,
        "teach_routine",
        name="Guten Morgen",
        trigger={"type": "time", "at": "08:00"},
        actions=[{"type": "say", "text": "Guten Morgen"}],
    )
    assert "Jeden Tag um 08:00" in changed.say
    assert len(book.routines()) == 1, "a correction replaces the open draft"

    confirmed = call(registry, store, alex, "confirm_routine")
    assert confirmed.outcome == "active"
    assert [r.status for r in book.routines()] == ["active"]
    assert call(registry, store, alex, "confirm_routine").outcome == "missing"


def test_guests_cannot_teach_and_unclear_routines_ask_back(store: Store) -> None:
    registry = builtin_tools()
    alex = store.add_person("Alex", "owner")

    assert (
        call(registry, store, None, "teach_routine", name="x", trigger={"type": "time"}).outcome == "denied"
    )
    missing_time = call(
        registry, store, alex, "teach_routine", name="x", trigger={"type": "time"}, actions=[]
    )
    assert missing_time.say == "Um welche Uhrzeit soll das passieren?"
    unknown_tool = call(
        registry,
        store,
        alex,
        "teach_routine",
        name="x",
        trigger={"type": "leave", "who": "ich"},
        actions=[{"type": "tool", "tool": "unlock_door"}],
    )
    assert unknown_tool.outcome == "incomplete" and "unlock_door" in unknown_tool.say
    assert routine_book(store).routines() == []


def test_routines_watching_others_or_using_owner_tools_need_the_owner(store: Store) -> None:
    lights = Lights()
    registry = registry_with_lights(lights)
    registry.register(
        Tool("disarm_alarm", "Schaltet den Alarm aus.", {"type": "object"}, lights, permission="owner")
    )
    alex = store.add_person("Alex", "owner")
    mia = store.add_person("Mia", "child")

    draft = call(
        registry,
        store,
        mia,
        "teach_routine",
        name="Alex kommt",
        trigger={"type": "arrive", "who": "Alex"},
        actions=[{"type": "say", "text": "Hallo Alex"}],
    )
    assert "muss sie danach der Besitzer im Kontrollzentrum freigeben" in draft.say
    waiting = call(registry, store, mia, "confirm_routine")
    assert waiting.outcome == "waiting"
    routine = routine_book(store).routines()[0]
    assert routine.status == "draft" and routine.waiting_for_owner

    client = TestClient(create_app(store=store))
    approved = client.post(f"/api/control/routines/{routine.id}/status", json={"status": "active"}).json()
    assert approved["status"] == "active"
    assert routine_book(store).routine(routine.id).approved_by == alex.id  # type: ignore[union-attr]

    call(
        registry,
        store,
        alex,
        "teach_routine",
        name="Alarm aus",
        trigger={"type": "arrive", "who": "ich"},
        actions=[{"type": "tool", "tool": "disarm_alarm"}],
    )
    assert call(registry, store, alex, "confirm_routine").outcome == "active", (
        "the owner approves own routines"
    )


def test_time_trigger_fires_once_on_the_right_days(store: Store) -> None:
    alex = store.add_person("Alex", "owner")
    active_routine(store, alex, trigger={"type": "time", "at": "07:00", "weekdays": [0, 1, 2, 3, 4]})
    speaker = Speaker()
    scheduler = RoutineScheduler(store, builtin_tools(), speaker, PresenceService())

    async def run() -> list[int]:
        counts = []
        for moment in (
            at(MONDAY, 6, 59, 58),
            at(MONDAY, 7, 0, 3),
            at(MONDAY, 7, 0, 8),
            at(MONDAY + timedelta(days=5), 6, 59),
            at(MONDAY + timedelta(days=5), 7, 1),
        ):
            counts.append(len(await scheduler.tick(moment)))
        return counts

    assert asyncio.run(run()) == [0, 1, 0, 0, 0]
    assert speaker.said == ["Guten Morgen"]
    run_log = routine_book(store).runs()
    assert [(r.result, r.trigger) for r in run_log] == [("done", "Montag bis Freitag um 07:00")]
    assert run_log[0].actions == [{"text": "sage ich «Guten Morgen»", "ok": True, "outcome": "spoken"}]


def test_a_missed_time_after_a_long_sleep_is_skipped(store: Store) -> None:
    alex = store.add_person("Alex", "owner")
    active_routine(store, alex)
    scheduler = RoutineScheduler(store, builtin_tools(), Speaker(), PresenceService())

    async def run() -> int:
        await scheduler.tick(at(MONDAY, 5))
        return len(await scheduler.tick(at(MONDAY, 9)))

    assert asyncio.run(run()) == 0


def test_cooldown_and_daily_limit(store: Store) -> None:
    alex = store.add_person("Alex", "owner")
    sara = store.add_person("Sara", "adult")
    presence = PresenceService(away_after=60)
    active_routine(
        store, alex, trigger={"type": "arrive", "who": "anyone"}, cooldown_minutes=30, daily_limit=2
    )
    scheduler = RoutineScheduler(store, builtin_tools(), Speaker(), presence)
    start = at(MONDAY, 12)

    async def visit(person: Person, moment: datetime) -> list[str]:
        presence.heard(person.id, moment.timestamp())
        runs = await scheduler.tick(moment)
        await scheduler.tick(moment + timedelta(minutes=2))  # nobody heard: they leave again
        return [run.result for run in runs]

    async def run() -> list[list[str]]:
        return [
            await visit(alex, start),
            await visit(sara, start + timedelta(minutes=10)),
            await visit(alex, start + timedelta(minutes=40)),
            await visit(sara, start + timedelta(minutes=80)),
        ]

    assert asyncio.run(run()) == [["done"], ["cooldown"], ["done"], ["limit"]]


def test_conditions_are_checked_and_logged(store: Store) -> None:
    alex = store.add_person("Alex", "owner")
    sara = store.add_person("Sara", "adult")
    presence = PresenceService(away_after=600)
    source = FakeSource({"light.flur": "on"})
    engine = RoutineEngine(store, builtin_tools(), Speaker(), presence, [source])
    routine = active_routine(
        store,
        alex,
        conditions=[
            {"type": "weekday", "days": [0]},
            {"type": "time_window", "from": "18:00", "to": "23:00"},
            {"type": "nobody_home"},
            {"type": "device_state", "entity": "light.flur", "state": "on"},
        ],
    )
    evening = at(MONDAY, 19)

    assert asyncio.run(engine.run(routine, Firing("Test"), evening)).result == "done"
    presence.heard(sara.id, evening.timestamp())
    skipped = asyncio.run(engine.run(routine, Firing("Test"), evening))
    assert skipped.result == "skipped"
    assert skipped.conditions == [
        {"text": "es Montag ist", "ok": True},
        {"text": "es zwischen 18:00 und 23:00 ist", "ok": True},
        {"text": "niemand mehr da ist", "ok": False},
        {"text": "light.flur «on» ist", "ok": True},
    ]
    assert skipped.actions == []
    assert asyncio.run(engine.check({"type": "person_home", "who": sara.id}, evening))
    assert asyncio.run(engine.check({"type": "person_away", "who": alex.id}, evening))
    assert not asyncio.run(
        engine.check({"type": "time_window", "from": "18:00", "to": "23:00"}, at(MONDAY, 9))
    )
    assert asyncio.run(engine.check({"type": "time_window", "from": "22:00", "to": "06:00"}, at(MONDAY, 2)))
    assert not asyncio.run(engine.check({"type": "outside_quiet_hours"}, at(MONDAY, 23)))


def test_actions_call_tools_with_the_runners_permissions_and_report(store: Store) -> None:
    lights = Lights()
    registry = registry_with_lights(lights)
    registry.register(Tool("lock", "Schliesst ab.", {"type": "object"}, lights, permission="owner"))
    alex = store.add_person("Alex", "owner")
    mia = store.add_person("Mia", "child")
    speaker = Speaker()
    engine = RoutineEngine(store, registry, speaker, PresenceService())
    routine = active_routine(
        store,
        mia,
        actions=[
            {"type": "tool", "tool": "lights_off", "arguments": {"area": "alle"}},
            {"type": "remind", "text": "Zähne putzen", "in_minutes": 5},
            {"type": "tool", "tool": "lock", "arguments": {}},
        ],
        report=True,
    )
    noon = at(MONDAY, 12)

    run = asyncio.run(engine.run(routine, Firing("Test"), noon))

    assert lights.calls == [("Mia", {"area": "alle"})], "an owner-only tool is refused to Mia"
    assert run.result == "partial"
    assert [a["outcome"] for a in run.actions] == ["switched", "planned", "denied"]
    assert run.actions[2]["ok"] is False
    reminder = store.reminders(mia.id)[0]
    assert reminder.text == "Zähne putzen" and reminder.due_at == noon.timestamp() + 300
    assert speaker.said == ["Ich habe drei Lichter ausgeschaltet."]
    assert OWNER_ONLY not in speaker.said

    routine_book(store).activate(routine.id, approved_by=alex.id)
    approved = routine_book(store).routine(routine.id)
    assert approved is not None
    asyncio.run(engine.run(approved, Firing("Test"), noon))
    assert lights.calls[-1] == ("Alex", {}), "after the owner's approval it runs with the owner's permissions"


def test_routines_stay_quiet_in_quiet_hours_and_without_a_connected_pebbo(store: Store) -> None:
    alex = store.add_person("Alex", "owner")
    routine = active_routine(store, alex)
    speaker = Speaker()

    night = asyncio.run(
        RoutineEngine(store, builtin_tools(), speaker).run(routine, Firing("Test"), at(MONDAY, 23))
    )
    alone = asyncio.run(
        RoutineEngine(store, builtin_tools(), None).run(routine, Firing("Test"), at(MONDAY, 12))
    )

    assert speaker.said == []
    assert night.actions[0]["outcome"] == "quiet hours" and night.result == "done"
    assert alone.actions[0]["outcome"] == "no Pebbo connected" and alone.result == "failed"


def test_leaving_last_and_device_triggers(store: Store) -> None:
    lights = Lights()
    alex = store.add_person("Alex", "owner")
    sara = store.add_person("Sara", "adult")
    presence = PresenceService(away_after=600)
    scheduler = RoutineScheduler(store, registry_with_lights(lights), Speaker(), presence)
    source = FakeSource({"binary_sensor.door": "off"})
    scheduler.add_state_source(source)
    active_routine(
        store,
        alex,
        name="Lichter aus",
        trigger={"type": "leave", "who": "last"},
        actions=[{"type": "tool", "tool": "lights_off", "arguments": {}}],
    )
    door = active_routine(
        store,
        alex,
        name="Tür",
        trigger={"type": "device", "entity": "binary_sensor.door", "to": "on"},
        actions=[{"type": "say", "text": "Die Tür ist offen"}],
    )
    noon = at(MONDAY, 12)

    async def run() -> list[list[str]]:
        presence.heard(alex.id, noon.timestamp())
        presence.heard(sara.id, (noon + timedelta(minutes=5)).timestamp())
        steps = [
            await scheduler.tick(noon + timedelta(minutes=6)),
            await scheduler.tick(noon + timedelta(minutes=11)),  # Alex leaves, Sara is still there
            await scheduler.tick(noon + timedelta(minutes=16)),  # Sara leaves last
        ]
        source.change("binary_sensor.door", "on")
        steps.append(await scheduler.tick(noon + timedelta(minutes=17)))
        source.change("binary_sensor.door", "off")
        steps.append(await scheduler.tick(noon + timedelta(minutes=18)))
        return [[run.trigger for run in runs] for runs in steps]

    assert asyncio.run(run()) == [[], [], ["Sara geht"], ["binary_sensor.door: off → on"], []]
    assert len(lights.calls) == 1
    assert routine_book(store).runs(door.id)[0].result == "done"


def test_trying_a_routine_only_shows_what_it_would_do(store: Store) -> None:
    registry = builtin_tools()
    alex = store.add_person("Alex", "owner")
    speaker = Speaker()
    call(
        registry,
        store,
        alex,
        "teach_routine",
        name="Feierabend",
        trigger={"type": "time", "at": "18:00"},
        actions=[{"type": "say", "text": "Feierabend!"}, {"type": "remind", "text": "Sport"}],
    )

    tried = call(registry, store, alex, "test_routine")

    assert (
        tried.say
        == "Wenn «Feierabend» jetzt liefe, würde ich «Feierabend!» sagen und dich an «Sport» erinnern."
    )
    assert speaker.said == [] and store.reminders() == []
    run = routine_book(store).runs()[0]
    assert run.dry_run and run.result == "test"


def test_list_pause_resume_and_discard_by_voice(store: Store) -> None:
    registry = builtin_tools()
    alex = store.add_person("Alex", "owner")
    active_routine(store, alex, name="Guten Morgen")
    active_routine(store, alex, name="Lichter aus beim Gehen", trigger={"type": "leave", "who": alex.id})

    listing = call(registry, store, alex, "list_routines")
    assert listing.say.startswith("Du hast 2 Routinen.") and "«Lichter aus beim Gehen»" in listing.say
    assert "Wenn du gehst" in listing.say
    assert call(registry, store, alex, "pause_routine", name="Lichter").outcome == "paused"
    assert "(pausiert)" in call(registry, store, alex, "list_routines").say
    assert call(registry, store, alex, "pause_routine", name="Lichter", resume=True).outcome == "active"
    assert call(registry, store, alex, "discard_routine", name="Guten Morgen").outcome == "deleted"
    assert [r.name for r in routine_book(store).routines()] == ["Lichter aus beim Gehen"]


def test_teaching_points_out_a_routine_with_the_same_trigger(store: Store) -> None:
    registry = builtin_tools()
    alex = store.add_person("Alex", "owner")
    active_routine(store, alex, name="Wecker")

    draft = call(
        registry,
        store,
        alex,
        "teach_routine",
        name="Kaffee",
        trigger={"type": "time", "at": "07:00"},
        actions=[{"type": "say", "text": "Kaffee?"}],
    )

    assert "Achtung, «Wecker» startet auch dann." in draft.say


def test_weekdays_and_descriptions(store: Store) -> None:
    alex = store.add_person("Alex", "owner")
    sara = store.add_person("Sara", "adult")

    assert parse_weekdays(["Mo", "Mi", "Fr"]) == [0, 2, 4]
    assert parse_weekdays("werktags") == [0, 1, 2, 3, 4]
    assert parse_weekdays(["Samstag", "Sonntag"]) == [5, 6]
    assert parse_weekdays([1, 7]) == [0, 6]
    assert parse_weekdays("täglich") == []
    with pytest.raises(RoutineError):
        parse_weekdays(["Blumentag"])
    text = describe(
        {"type": "leave", "who": alex.id},
        [{"type": "nobody_home"}, {"type": "person_away", "who": sara.id}],
        [{"type": "say", "text": "Tschüss"}, {"type": "remind", "text": "Schlüssel", "in_minutes": 0}],
        True,
        store,
        alex,
    )
    assert text == (
        "Wenn du gehst und niemand mehr da ist und Sara weg ist, sage ich «Tschüss» und erinnere dich an "
        "«Schlüssel». Danach sage ich, was ich getan habe."
    )


def test_sun_times_are_plausible_for_zurich() -> None:
    zone = clock.timezone()
    sunrise, sunset = sun_times(datetime(2026, 6, 21).date(), 47.37, 8.54, zone)

    assert sunrise is not None and sunset is not None
    assert abs((sunrise - datetime(2026, 6, 21, 5, 30, tzinfo=zone)).total_seconds()) < 10 * 60
    assert abs((sunset - datetime(2026, 6, 21, 21, 26, tzinfo=zone)).total_seconds()) < 10 * 60


def test_sun_triggers_need_a_location(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = builtin_tools()
    alex = store.add_person("Alex", "owner")
    monkeypatch.delenv("PEBBO_LATITUDE", raising=False)

    refused = call(
        registry,
        store,
        alex,
        "teach_routine",
        name="x",
        trigger={"type": "sunset"},
        actions=[{"type": "say", "text": "x"}],
    )
    assert "Standort" in refused.say

    monkeypatch.setenv("PEBBO_LATITUDE", "47.37")
    monkeypatch.setenv("PEBBO_LONGITUDE", "8.54")
    taught = call(
        registry,
        store,
        alex,
        "teach_routine",
        name="Abend",
        trigger={"type": "sunset", "offset_minutes": -15},
        actions=[{"type": "say", "text": "Die Sonne geht unter"}],
    )
    assert "Jeden Tag 15 Minuten vor Sonnenuntergang sage ich" in taught.say


def test_control_api_lists_tests_and_deletes_routines(store: Store) -> None:
    alex = store.add_person("Alex", "owner")
    routine = active_routine(store, alex, name="Guten Morgen")
    client = TestClient(create_app(store=store))

    listed = client.get("/api/control/routines").json()
    assert listed[0]["description"] == "Jeden Tag um 07:00 sage ich «Guten Morgen»."
    paused = client.post(f"/api/control/routines/{routine.id}/status", json={"status": "paused"}).json()
    assert paused["status"] == "paused"
    tested = client.post(f"/api/control/routines/{routine.id}/test").json()
    assert tested["run"]["result"] == "test" and "würde ich «Guten Morgen» sagen" in tested["say"]
    runs = client.get("/api/control/routine-runs", params={"routine_id": routine.id}).json()
    assert [run["result"] for run in runs] == ["test"]
    assert client.delete(f"/api/control/routines/{routine.id}").status_code == 204
    assert client.get("/api/control/routines").json() == []
    assert client.delete(f"/api/control/routines/{routine.id}").status_code == 404


def test_the_action_agent_passes_only_words_and_the_structurer_fills_the_routine(store: Store) -> None:
    from pebbo.routines.structure import RoutineRequest

    requests: list[RoutineRequest] = []

    async def structure(request: RoutineRequest, schema: dict[str, Any]) -> dict[str, Any] | None:
        requests.append(request)
        assert schema["name"] == "teach_routine" and "trigger" in schema["parameters"]["properties"]
        if "kaputt" in request.text:
            return None
        hour = "08:00" if request.draft else "07:00"
        return {
            "name": "Guten Morgen",
            "trigger": {"type": "time", "at": hour},
            "actions": [{"type": "tool", "tool": "lights_off", "arguments": {}}],
        }

    registry = builtin_tools(structure)
    registry.register(Tool("lights_off", "Schaltet Lichter aus. Mit Raum.", {"type": "object"}, Lights()))
    alex = store.add_person("Alex", "owner")
    short = next(s for s in registry.schemas() if s["function"]["name"] == "teach_routine")
    assert list(short["function"]["parameters"]["properties"]) == ["text"]

    draft = call(registry, store, alex, "teach_routine", text="Jeden Tag um sieben Licht aus")
    assert draft.outcome == "draft" and "07:00" in draft.say
    assert requests[0].person == "Alex" and requests[0].draft == ""
    assert ("lights_off", "Schaltet Lichter aus") in requests[0].tools
    assert not any(name == "teach_routine" for name, _ in requests[0].tools)

    changed = call(registry, store, alex, "teach_routine", text="lieber um acht")
    assert "08:00" in changed.say and "07:00" in requests[1].draft
    assert len(routine_book(store).routines()) == 1

    failed = call(registry, store, alex, "teach_routine", text="kaputt")
    assert failed.outcome == "incomplete" and not failed.ok


def test_decisions_and_summaries_reach_compute_devices_on_the_home_network() -> None:
    from pytest_socket import SocketConnectBlockedError

    from pebbo.voice.ollama_setup import llm_request

    with pytest.raises(ValueError):
        llm_request("http://8.8.8.8:11434/v1", "/v1/chat/completions", {}, 1)
    with pytest.raises(ValueError):
        llm_request("ftp://192.168.1.30", "/v1/chat/completions", {}, 1)
    # A home network address is accepted; the test network guard then refuses the connection.
    with pytest.raises(SocketConnectBlockedError):
        llm_request("http://192.168.1.30:11434/v1", "/v1/chat/completions", {}, 1)


def test_tool_actions_are_read_back_in_words_without_empty_arguments(store: Store) -> None:
    lights = Lights()
    registry = registry_with_lights(lights)
    alex = store.add_person("Alex", "owner")
    assert call(registry, store, alex, "discard_routine").outcome == "missing"

    draft = call(
        registry,
        store,
        alex,
        "teach_routine",
        name="Licht",
        trigger={"type": "time", "at": "22:00"},
        actions=[
            {
                "type": "tool",
                "tool": "lights_off",
                "arguments": {"area": "", "domain": ["light"]},
                "spoken": "alle Lichter ausschalten",
            },
            {"type": "say", "spoken": "Gute Nacht"},
        ],
    )
    assert "werde ich alle Lichter ausschalten" in draft.say and "«Gute Nacht»" in draft.say
    routine = routine_book(store).routines()[0]
    assert routine.actions[0]["arguments"] == {"domain": ["light"]}


def test_device_routines_get_the_device_list_fitting_arguments_and_proper_german(store: Store) -> None:
    # Seen with the real model: floor "Geschoss", domain "light" instead of a list, and
    # "werde ich Licht in der Küche an" read back, then "würde ich Licht in der Küche an werde".
    from pebbo.routines.structure import RoutineRequest, prompt
    from pebbo.tools.registry import ContextSource

    requests: list[RoutineRequest] = []

    async def structure(request: RoutineRequest, _schema: dict[str, Any]) -> dict[str, Any] | None:
        requests.append(request)
        arguments = {"name": "Küchenlicht", "floor": "Geschoss", "domain": "light", "color": "rot"}
        return {
            "name": "Küche_morgens",
            "trigger": {"type": "time", "at": "07:30"},
            "actions": [
                {"type": "tool", "tool": "turn_on", "arguments": arguments, "spoken": "Licht in der Küche an"}
            ],
        }

    async def devices(_context: Any) -> str:
        return "Geräte im Haus:\n- Bereich Küche:\n  - Küchenlicht: aus"

    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "floor": {"type": "string"},
            "domain": {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}]},
        },
    }
    registry = builtin_tools(structure)
    registry.register(Tool("turn_on", "Schaltet ein.", schema, Lights()))
    registry.add_context(ContextSource("mcp:Test", devices))
    alex = store.add_person("Alex", "owner")

    draft = call(registry, store, alex, "teach_routine", text="Jeden Morgen um halb acht Küchenlicht an")
    assert "werde ich Licht in der Küche anschalten." in draft.say
    assert requests[0].devices == ["Geräte im Haus:\n- Bereich Küche:\n  - Küchenlicht: aus"]
    assert "  - Küchenlicht: aus" in prompt(requests[0])
    routine = routine_book(store).routines()[0]
    assert routine.actions[0]["arguments"] == {
        "name": "Küchenlicht",
        "floor": "Geschoss",
        "domain": ["light"],
    }
    assert routine.name == "Küche morgens"
    tested = call(registry, store, alex, "test_routine", name="Küche morgens")
    assert "würde ich Licht in der Küche anschalten." in tested.say
