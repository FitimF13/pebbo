"""Who is near Pebbo, from local signals only.

For now the only signal is the voice: a person whose voice Pebbo recognises is "near" and
counts as at home. After ``PEBBO_PRESENCE_AWAY_MINUTES`` (60 by default) without hearing
them, they count as "away". Someone Pebbo has not heard since it started is "unknown".
Phones on the home Wi-Fi and the phone app follow in phase 4 (see docs/features.md).

Arriving and leaving are events that routines react to (see ``pebbo.routines``). Presence
lives in memory only: after a restart everyone is unknown until Pebbo hears them again.
"""

from __future__ import annotations

import os
import threading
import time
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pebbo.store import Store

PresenceKind = Literal["arrive", "leave"]
PresenceStatus = Literal["near", "away", "unknown"]


def away_after_seconds() -> float:
    try:
        minutes = float(os.environ.get("PEBBO_PRESENCE_AWAY_MINUTES", "60"))
    except ValueError:
        minutes = 60.0
    return max(1.0, minutes) * 60


@dataclass(frozen=True)
class PresenceEvent:
    kind: PresenceKind
    person_id: int
    at: float


Listener = Callable[[PresenceEvent], None]


class PresenceService:
    """Tracks when each person was last heard and reports arrivals and departures."""

    def __init__(self, away_after: float | None = None) -> None:
        self.away_after = away_after if away_after is not None else away_after_seconds()
        self._lock = threading.Lock()
        self._last_heard: dict[int, float] = {}
        self._near: set[int] = set()
        self._listeners: list[Listener] = []

    def subscribe(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def unsubscribe(self, listener: Listener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def heard(self, person_id: int, at: float | None = None) -> None:
        """A person's voice was recognised. Reports an arrival if they were not near."""
        at = time.time() if at is None else at
        with self._lock:
            arrived = person_id not in self._near
            self._near.add(person_id)
            self._last_heard[person_id] = max(at, self._last_heard.get(person_id, at))
        if arrived:
            self._emit(PresenceEvent("arrive", person_id, at))

    def update(self, at: float | None = None) -> list[PresenceEvent]:
        """Mark people as away who were not heard for a while. Returns the departures."""
        at = time.time() if at is None else at
        with self._lock:
            gone = [pid for pid in self._near if at - self._last_heard.get(pid, at) >= self.away_after]
            self._near.difference_update(gone)
        events = [PresenceEvent("leave", pid, at) for pid in sorted(gone)]
        for event in events:
            self._emit(event)
        return events

    def status(self, person_id: int) -> PresenceStatus:
        with self._lock:
            if person_id in self._near:
                return "near"
            return "away" if person_id in self._last_heard else "unknown"

    def is_near(self, person_id: int) -> bool:
        return self.status(person_id) == "near"

    def near_people(self) -> set[int]:
        with self._lock:
            return set(self._near)

    def last_heard(self, person_id: int) -> float | None:
        with self._lock:
            return self._last_heard.get(person_id)

    def _emit(self, event: PresenceEvent) -> None:
        for listener in list(self._listeners):
            listener(event)


_services: weakref.WeakKeyDictionary[Store, PresenceService] = weakref.WeakKeyDictionary()
_services_lock = threading.Lock()


def presence_for(store: Store) -> PresenceService:
    """The presence service of the Pebbo instance that owns this database."""
    with _services_lock:
        service = _services.get(store)
        if service is None:
            service = _services[store] = PresenceService()
        return service
