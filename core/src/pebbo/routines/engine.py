"""Running routines: triggers, conditions, actions, cooldowns and the run log.

The engine needs no language model. Triggers are checked by :class:`RoutineScheduler`,
which runs in the core next to the reminder scheduler. Device states come from
:class:`StateSource` objects, for example a Home Assistant connector, which call
:meth:`RoutineScheduler.add_state_source` once they are connected.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

from loguru import logger

from pebbo import clock
from pebbo.presence import PresenceEvent, PresenceService, presence_for
from pebbo.routines.model import Names, describe_action, describe_condition, describe_trigger
from pebbo.routines.storage import Routine, RoutineBook, RoutineRun, RunResult, routine_book
from pebbo.routines.sun import location, sun_times
from pebbo.store import Person, Store
from pebbo.tools.registry import ToolContext, ToolRegistry

# Says a text in every connected conversation and returns in how many.
Speak = Callable[[str], Awaitable[int]]
# A time trigger missed by more than this, for example while the computer slept, is skipped.
CATCH_UP = timedelta(minutes=10)


@dataclass(frozen=True)
class StateChange:
    """A device changed its state, for example ``light.wohnzimmer`` from ``off`` to ``on``."""

    entity: str
    old: str | None
    new: str | None


class StateSource(Protocol):
    """Where device states come from, for example Home Assistant.

    ``get_state`` returns ``None`` for an entity the source does not know. The source calls
    every subscribed listener when a state changes; listeners may be called from any thread.
    """

    async def get_state(self, entity: str) -> str | None: ...

    def subscribe(self, listener: Callable[[StateChange], None]) -> None: ...


@dataclass(frozen=True)
class Firing:
    """What made a routine start."""

    text: str
    person_id: int | None = None


@dataclass
class _Outcome:
    conditions: list[dict[str, Any]] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)


class RoutineEngine:
    """Checks the conditions of a routine and carries out its actions."""

    def __init__(
        self,
        store: Store,
        registry: ToolRegistry,
        speak: Speak | None = None,
        presence: PresenceService | None = None,
        sources: Sequence[StateSource] = (),
    ) -> None:
        self.store = store
        self.book: RoutineBook = routine_book(store)
        self.registry = registry
        self.speak = speak
        self.presence = presence or presence_for(store)
        self.sources: list[StateSource] = list(sources)

    async def device_state(self, entity: str) -> str | None:
        for source in self.sources:
            try:
                state = await source.get_state(entity)
            except Exception:
                logger.exception("Could not read the state of {}", entity)
                continue
            if state is not None:
                return state
        return None

    async def check(self, condition: dict[str, Any], moment: datetime) -> bool:
        kind = condition["type"]
        if kind == "weekday":
            return not condition.get("days") or moment.weekday() in condition["days"]
        if kind == "time_window":
            start = datetime.strptime(condition["from"], "%H:%M").time()
            end = datetime.strptime(condition["to"], "%H:%M").time()
            return clock.in_window(moment, start, end)
        if kind == "quiet_hours":
            return clock.in_quiet_hours(moment)
        if kind == "outside_quiet_hours":
            return not clock.in_quiet_hours(moment)
        if kind == "person_home":
            return self.presence.is_near(int(condition["who"]))
        if kind == "person_away":
            return not self.presence.is_near(int(condition["who"]))
        if kind == "nobody_home":
            return not self.presence.near_people()
        if kind == "someone_home":
            return bool(self.presence.near_people())
        if kind == "device_state":
            state = await self.device_state(condition["entity"])
            return state is not None and state.lower() == str(condition["state"]).lower()
        return False

    def runner(self, routine: Routine) -> Person | None:
        """Whose permissions the actions use: the approving owner, otherwise the person who taught it."""
        if routine.approved_by is not None:
            approver = self.store.person(routine.approved_by)
            if approver is not None:
                return approver
        return self.store.person(routine.person_id)

    async def fire(self, routine: Routine, firing: Firing, moment: datetime | None = None) -> RoutineRun:
        """Run a routine because its trigger fired, respecting its cooldown and daily limit."""
        moment = moment or clock.now()
        stamp = moment.timestamp()
        # Read it again: an earlier event in the same check may just have run it.
        routine = self.book.routine(routine.id) or routine
        if routine.last_run_at is not None and stamp - routine.last_run_at < routine.cooldown_minutes * 60:
            return self.book.record_run(routine.id, firing.text, [], [], "cooldown", started_at=stamp)
        midnight = moment.replace(hour=0, minute=0, second=0, microsecond=0)
        if self.book.executed_since(routine.id, midnight.timestamp()) >= routine.daily_limit:
            return self.book.record_run(routine.id, firing.text, [], [], "limit", started_at=stamp)
        return await self.run(routine, firing, moment)

    async def run(
        self, routine: Routine, firing: Firing, moment: datetime | None = None, *, dry_run: bool = False
    ) -> RoutineRun:
        """Check the conditions and act, or with ``dry_run`` only show what would happen."""
        moment = moment or clock.now()
        names = Names(self.store, self.store.person(routine.person_id))
        outcome = _Outcome()
        met = True
        for condition in routine.conditions:
            ok = await self.check(condition, moment)
            outcome.conditions.append({"text": describe_condition(condition, names), "ok": ok})
            met = met and ok
        result: RunResult
        if dry_run:
            outcome.actions = [
                {"text": describe_action(action, True), "ok": True, "outcome": "would"}
                for action in routine.actions
            ]
            result = "test"
        elif not met:
            result = "skipped"
        else:
            await self._act(routine, moment, outcome)
            failures = sum(1 for action in outcome.actions if not action["ok"])
            result = "done" if failures == 0 else "failed" if failures == len(outcome.actions) else "partial"
        run = self.book.record_run(
            routine.id,
            firing.text,
            outcome.conditions,
            outcome.actions,
            result,
            started_at=moment.timestamp(),
            dry_run=dry_run,
        )
        if not dry_run:
            logger.info("Routine {} ran: {}", routine.id, result)
        return run

    async def _act(self, routine: Routine, moment: datetime, outcome: _Outcome) -> None:
        person = self.runner(routine)
        reports: list[str] = []
        for action in routine.actions:
            entry: dict[str, Any] = {"text": describe_action(action, True)}
            kind = action["type"]
            if kind == "say":
                entry.update(await self._say(action["text"], moment))
            elif kind == "remind":
                if person is None:
                    entry.update(ok=False, outcome="no person")
                else:
                    due = moment.timestamp() + int(action.get("in_minutes", 0)) * 60
                    self.store.add_reminder(person.id, action["text"], due)
                    entry.update(ok=True, outcome="planned")
            else:
                context = ToolContext(self.store, person, None)
                result = await self.registry.call(action["tool"], dict(action.get("arguments", {})), context)
                entry.update(ok=result.ok, outcome=result.outcome or ("done" if result.ok else "failed"))
                if result.say:
                    entry["say"] = result.say
                    if result.ok:
                        reports.append(result.say)
            outcome.actions.append(entry)
        if routine.report and reports:
            await self._say(" ".join(reports), moment)

    async def _say(self, text: str, moment: datetime) -> dict[str, Any]:
        if clock.in_quiet_hours(moment):
            return {"ok": True, "outcome": "quiet hours"}
        if self.speak is None:
            return {"ok": False, "outcome": "no Pebbo connected"}
        heard = await self.speak(text)
        return {"ok": heard > 0, "outcome": "spoken" if heard else "no Pebbo connected"}


def _scheduled(routine: Routine, day: datetime) -> datetime | None:
    """When a time or sun routine is due on the day of ``day``, or ``None``."""
    trigger = routine.trigger
    weekdays = trigger.get("weekdays") or []
    if weekdays and day.weekday() not in weekdays:
        return None
    if trigger["type"] == "time":
        hour, minute = (int(part) for part in trigger["at"].split(":"))
        return day.replace(hour=hour, minute=minute, second=0, microsecond=0)
    place = location()
    if place is None or day.tzinfo is None:
        return None
    sunrise, sunset = sun_times(day.date(), place[0], place[1], day.tzinfo)
    moment = sunrise if trigger["type"] == "sunrise" else sunset
    if moment is None:
        return None
    return (moment + timedelta(minutes=int(trigger.get("offset_minutes", 0)))).replace(
        second=0, microsecond=0
    )


def due_between(routine: Routine, after: datetime, until: datetime) -> datetime | None:
    """The scheduled moment of a time or sun routine in ``(after, until]``, if any."""
    day = after
    while day.date() <= until.date():
        moment = _scheduled(routine, day)
        if moment is not None and after < moment <= until:
            return moment
        day = (day + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return None


def scheduled_today(routine: Routine, reference: datetime) -> datetime | None:
    """When an active time or sun routine runs on the day of ``reference``."""
    if routine.trigger["type"] not in ("time", "sunrise", "sunset"):
        return None
    return _scheduled(routine, reference)


class RoutineScheduler:
    """Watches the triggers of all active routines and runs them.

    Every few seconds it checks time and sun triggers, the presence service's arrivals and
    departures, and the device changes reported by state sources.
    """

    def __init__(
        self,
        store: Store,
        registry: ToolRegistry,
        speak: Speak | None = None,
        presence: PresenceService | None = None,
        interval: float = 5.0,
    ) -> None:
        self.engine = RoutineEngine(store, registry, speak, presence)
        self._interval = interval
        self._events: deque[PresenceEvent | StateChange] = deque(maxlen=200)
        self._events_lock = threading.Lock()
        self._last_tick: datetime | None = None
        self._task: asyncio.Task[None] | None = None
        self.engine.presence.subscribe(self._queue)

    @property
    def book(self) -> RoutineBook:
        return self.engine.book

    def add_state_source(self, source: StateSource) -> None:
        """Use a source of device states for device triggers and conditions."""
        self.engine.sources.append(source)
        source.subscribe(self._queue)

    def _queue(self, event: PresenceEvent | StateChange) -> None:
        with self._events_lock:
            self._events.append(event)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self.engine.presence.unsubscribe(self._queue)
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def tick(self, now: datetime | None = None) -> list[RoutineRun]:
        """Check all triggers once. Returns the runs it caused."""
        now = now or clock.now()
        self.engine.presence.update(now.timestamp())
        with self._events_lock:
            events = list(self._events)
            self._events.clear()
        active = self.book.routines(status="active")
        runs: list[RoutineRun] = []
        for event in events:
            for routine in active:
                firing = self._matches(routine, event)
                if firing is not None:
                    runs.append(await self.engine.fire(routine, firing, now))
        previous, self._last_tick = self._last_tick, now
        if previous is not None:
            after = max(previous, now - CATCH_UP)
            for routine in active:
                if routine.trigger["type"] in ("time", "sunrise", "sunset"):
                    moment = due_between(routine, after, now)
                    if moment is not None:
                        text = describe_trigger(routine.trigger, Names(self.engine.store, None))[0]
                        runs.append(await self.engine.fire(routine, Firing(text[:1].upper() + text[1:]), now))
        return runs

    def _matches(self, routine: Routine, event: PresenceEvent | StateChange) -> Firing | None:
        trigger = routine.trigger
        if isinstance(event, StateChange):
            if trigger["type"] != "device" or trigger["entity"] != event.entity or event.old == event.new:
                return None
            wanted = trigger.get("to")
            if wanted and (event.new or "").lower() != str(wanted).lower():
                return None
            return Firing(f"{event.entity}: {event.old} → {event.new}")
        if trigger["type"] != event.kind:
            return None
        who = trigger["who"]
        near = self.engine.presence.near_people()
        if who == "last" and near:
            return None
        if who == "first" and near != {event.person_id}:
            return None
        if isinstance(who, int) and who != event.person_id:
            return None
        person = self.engine.store.person(event.person_id)
        name = person.name if person else "Jemand"
        return Firing(f"{name} {'kommt' if event.kind == 'arrive' else 'geht'}", event.person_id)

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                logger.exception("Routine check failed")
            await asyncio.sleep(self._interval)
