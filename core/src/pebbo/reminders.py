"""Deliver due reminders.

Pebbo speaks a due reminder in every connected conversation. Without a connected PC app the
reminder stays pending and is spoken as soon as one connects. Push to the phone and
presence-based delivery follow in phase 4.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import datetime

from loguru import logger

from pebbo import clock
from pebbo.store import Person, Reminder, Store

Speaker = Callable[[str], Awaitable[None]]
LATE_AFTER_SECONDS = 120


def reminder_text(reminder: Reminder, person: Person | None, now: float) -> str:
    """What Pebbo says for a due reminder."""
    name = f"{person.name}, " if person else ""
    if now - reminder.due_at > LATE_AFTER_SECONDS:
        due = datetime.fromtimestamp(reminder.due_at, clock.timezone())
        return f"{name}du hattest eine Erinnerung für {clock.spoken_datetime(due)}: {reminder.text}."
    return f"{name}ich soll dich erinnern: {reminder.text}."


class ReminderScheduler:
    """Checks for due reminders every second and hands them to connected conversations."""

    def __init__(self, store: Store, interval: float = 1.0) -> None:
        self._store = store
        self._interval = interval
        self._speakers: set[Speaker] = set()
        self._task: asyncio.Task[None] | None = None

    def connect(self, speaker: Speaker) -> None:
        self._speakers.add(speaker)

    def disconnect(self, speaker: Speaker) -> None:
        self._speakers.discard(speaker)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    async def announce(self, text: str) -> int:
        """Say something in every connected conversation, for example for a routine.

        Returns in how many conversations it was said, 0 when no PC app or body is connected.
        """
        speakers = list(self._speakers)
        for speak in speakers:
            await speak(text)
        return len(speakers)

    async def deliver_due(self, now: float | None = None) -> int:
        """Speak every due reminder in the connected conversations. Returns how many were delivered."""
        if not self._speakers:
            return 0
        now = now or time.time()
        delivered = 0
        for reminder in self._store.due_reminders(now):
            text = reminder_text(reminder, self._store.person(reminder.person_id), now)
            for speak in list(self._speakers):
                await speak(text)
            self._store.mark_delivered(reminder.id)
            delivered += 1
            logger.info("Delivered reminder {}", reminder.id)
        return delivered

    async def _run(self) -> None:
        while True:
            try:
                await self.deliver_due()
            except Exception:
                logger.exception("Reminder delivery failed")
            await asyncio.sleep(self._interval)
