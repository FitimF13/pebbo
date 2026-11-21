"""Which computer Pebbo thinks on: the model router.

The owner lists compute devices in the control centre: this computer and, for example, the
gaming PC as a worker or a small always-on box. Each runs Ollama on the home network. Pebbo
checks them regularly and uses the first one in the owner's order that answers and has its
model. When the gaming PC is switched off, Pebbo keeps working on the next device, with a
smaller model and simpler answers. A new conversation always starts on the best device that
is available at that moment.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from loguru import logger

from pebbo.netguard import is_local_address
from pebbo.store import Store

SCHEMA = """
CREATE TABLE IF NOT EXISTS compute_devices (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    base_url TEXT NOT NULL,
    model TEXT NOT NULL,
    position INTEGER NOT NULL,
    created_at REAL NOT NULL
);
"""
CHECK_SECONDS = 20.0
_TIMEOUT = 1.5


@dataclass(frozen=True)
class ComputeDevice:
    """A computer that runs the language model. ``id`` 0 is this computer from the settings."""

    id: int
    name: str
    base_url: str
    model: str
    position: int


def model_available(base_url: str, model: str, timeout: float = _TIMEOUT) -> bool:
    """Whether the Ollama at ``base_url`` (OpenAI-style, ending in /v1) answers and has ``model``."""
    url = f"{base_url.rstrip('/')}/models"
    if not url.startswith(("http://", "https://")):
        return False
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - scheme checked
            listed = json.loads(response.read() or b"{}")
    except (OSError, urllib.error.URLError, ValueError):
        return False
    names = {str(entry.get("id", "")) for entry in listed.get("data", []) if isinstance(entry, dict)}
    return model in names or f"{model}:latest" in names


class ModelRouter:
    """Keeps track of reachable compute devices and picks the one to use."""

    def __init__(self, store: Store, default: ComputeDevice, check: Any = model_available) -> None:
        self.store = store
        self.default = default
        self._check = check
        self._reachable: dict[int, bool] = {}
        self._checked_at = 0.0
        self._task: asyncio.Task[None] | None = None
        with store._lock, store._db:
            store._db.executescript(SCHEMA)

    # Devices --------------------------------------------------------------

    def devices(self) -> list[ComputeDevice]:
        with self.store._lock:
            rows = self.store._db.execute("SELECT * FROM compute_devices ORDER BY position, id").fetchall()
        return [self.default, *(self._device(row) for row in rows)]

    def add(self, name: str, base_url: str, model: str) -> ComputeDevice:
        host = urlparse(base_url).hostname or ""
        if not base_url.startswith(("http://", "https://")) or not host:
            raise ValueError("Die Adresse muss mit http:// beginnen.")
        if not is_local_address(host) and host != "localhost":
            raise ValueError("Rechner müssen im Heimnetz oder im privaten VPN sein.")
        with self.store._lock, self.store._db:
            position = int(
                self.store._db.execute(
                    "SELECT COALESCE(MAX(position), 0) + 1 FROM compute_devices"
                ).fetchone()[0]
            )
            cursor = self.store._db.execute(
                "INSERT INTO compute_devices (name, base_url, model, position, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (name.strip()[:40], base_url.rstrip("/"), model.strip(), position, time.time()),
            )
            row = self.store._db.execute(
                "SELECT * FROM compute_devices WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        self._checked_at = 0.0
        return self._device(row)

    def remove(self, device_id: int) -> bool:
        with self.store._lock, self.store._db:
            removed = (
                self.store._db.execute("DELETE FROM compute_devices WHERE id = ?", (device_id,)).rowcount > 0
            )
        self._reachable.pop(device_id, None)
        return removed

    def move(self, device_id: int, position: int) -> None:
        with self.store._lock, self.store._db:
            self.store._db.execute(
                "UPDATE compute_devices SET position = ? WHERE id = ?", (position, device_id)
            )

    @staticmethod
    def _device(row: sqlite3.Row) -> ComputeDevice:
        return ComputeDevice(row["id"], row["name"], row["base_url"], row["model"], row["position"])

    # Choosing -------------------------------------------------------------

    def refresh(self) -> None:
        """Check every device once. Blocking: call it in a thread."""
        reachable = {device.id: bool(self._check(device.base_url, device.model)) for device in self.devices()}
        changed = reachable != self._reachable
        self._reachable, self._checked_at = reachable, time.monotonic()
        if changed:
            up = [d.name for d in self.devices() if reachable.get(d.id)]
            logger.info("Compute devices available: {}", ", ".join(up) or "none")

    def reachable(self, device: ComputeDevice) -> bool | None:
        """True or False after a check, None if not checked yet."""
        return self._reachable.get(device.id)

    def current(self) -> ComputeDevice:
        """The first reachable device in the owner's order, or this computer if none answers."""
        for device in self.devices():
            if self._reachable.get(device.id):
                return device
        return self.default

    async def start(self) -> None:
        async def loop() -> None:
            while True:
                try:
                    await asyncio.to_thread(self.refresh)
                except Exception:  # Checking must never stop Pebbo.
                    logger.exception("Could not check the compute devices")
                await asyncio.sleep(CHECK_SECONDS)

        self._task = asyncio.create_task(loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
