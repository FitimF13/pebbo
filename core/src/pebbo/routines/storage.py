"""Routines and their run log, in their own tables of the instance database."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import weakref
from dataclasses import dataclass
from typing import Any, Literal

from pebbo.store import Store

RoutineStatus = Literal["draft", "active", "paused"]
# done: all actions ran. partial or failed: some or all actions failed. skipped: a condition
# was not met. cooldown and limit: the routine ran too recently or too often today. test: a
# dry run that only showed what would happen.
RunResult = Literal["done", "partial", "failed", "skipped", "cooldown", "limit", "test"]
EXECUTED: tuple[RunResult, ...] = ("done", "partial", "failed")
KEEP_RUNS = 200

SCHEMA = """
CREATE TABLE IF NOT EXISTS routines (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    text TEXT NOT NULL,
    trigger TEXT NOT NULL,
    conditions TEXT NOT NULL,
    actions TEXT NOT NULL,
    report INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN ('draft', 'active', 'paused')),
    needs_owner INTEGER NOT NULL DEFAULT 0,
    confirmed_at REAL,
    approved_by INTEGER REFERENCES people(id) ON DELETE SET NULL,
    cooldown_minutes INTEGER NOT NULL,
    daily_limit INTEGER NOT NULL,
    created_at REAL NOT NULL,
    last_run_at REAL
);
CREATE TABLE IF NOT EXISTS routine_runs (
    id INTEGER PRIMARY KEY,
    routine_id INTEGER NOT NULL REFERENCES routines(id) ON DELETE CASCADE,
    started_at REAL NOT NULL,
    trigger TEXT NOT NULL,
    conditions TEXT NOT NULL,
    actions TEXT NOT NULL,
    result TEXT NOT NULL,
    dry_run INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS routine_runs_by_routine ON routine_runs (routine_id, started_at);
"""


@dataclass(frozen=True)
class Routine:
    id: int
    person_id: int
    name: str
    text: str
    trigger: dict[str, Any]
    conditions: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    report: bool
    status: RoutineStatus
    # Routines that affect others, watch other people or use owner-only tools need the owner.
    needs_owner: bool
    # When the person said yes. A draft with a yes waits for the owner's approval.
    confirmed_at: float | None
    approved_by: int | None
    cooldown_minutes: int
    daily_limit: int
    created_at: float
    last_run_at: float | None

    @property
    def waiting_for_owner(self) -> bool:
        return self.status == "draft" and self.confirmed_at is not None


@dataclass(frozen=True)
class RoutineRun:
    id: int
    routine_id: int
    started_at: float
    trigger: str
    # Each checked condition as {"text": ..., "ok": bool}.
    conditions: list[dict[str, Any]]
    # Each action as {"text": ..., "ok": bool, "outcome": ...}.
    actions: list[dict[str, Any]]
    result: RunResult
    dry_run: bool


class RoutineBook:
    """Thread-safe access to the routine tables."""

    def __init__(self, store: Store) -> None:
        self._db, self._lock = store.extension(SCHEMA)

    def add(
        self,
        person_id: int,
        name: str,
        text: str,
        trigger: dict[str, Any],
        conditions: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        *,
        report: bool = False,
        needs_owner: bool = False,
        cooldown_minutes: int,
        daily_limit: int,
        status: RoutineStatus = "draft",
    ) -> Routine:
        with self._lock, self._db:
            cursor = self._db.execute(
                "INSERT INTO routines (person_id, name, text, trigger, conditions, actions, report, status, "
                "needs_owner, cooldown_minutes, daily_limit, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    person_id,
                    name.strip() or "Routine",
                    text.strip(),
                    json.dumps(trigger, ensure_ascii=False),
                    json.dumps(conditions, ensure_ascii=False),
                    json.dumps(actions, ensure_ascii=False),
                    int(report),
                    status,
                    int(needs_owner),
                    cooldown_minutes,
                    daily_limit,
                    time.time(),
                ),
            )
        routine = self.routine(int(cursor.lastrowid or 0))
        if routine is None:
            raise RuntimeError("The new routine could not be read back.")
        return routine

    def routine(self, routine_id: int) -> Routine | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM routines WHERE id = ?", (routine_id,)).fetchone()
        return _routine(row) if row else None

    def routines(self, person_id: int | None = None, status: RoutineStatus | None = None) -> list[Routine]:
        query = "SELECT * FROM routines WHERE 1 = 1"
        values: list[object] = []
        if person_id is not None:
            query += " AND person_id = ?"
            values.append(person_id)
        if status is not None:
            query += " AND status = ?"
            values.append(status)
        with self._lock:
            rows = self._db.execute(query + " ORDER BY id", values).fetchall()
        return [_routine(row) for row in rows]

    def drafts(self, person_id: int) -> list[Routine]:
        """The person's drafts still waiting for their own yes, newest first."""
        return [r for r in reversed(self.routines(person_id, "draft")) if r.confirmed_at is None]

    def confirm(self, routine_id: int) -> None:
        """The person said yes, the routine now waits for the owner."""
        with self._lock, self._db:
            self._db.execute("UPDATE routines SET confirmed_at = ? WHERE id = ?", (time.time(), routine_id))

    def activate(self, routine_id: int, approved_by: int | None = None) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE routines SET status = 'active', confirmed_at = COALESCE(confirmed_at, ?), "
                "approved_by = COALESCE(?, approved_by) WHERE id = ?",
                (time.time(), approved_by, routine_id),
            )

    def set_status(self, routine_id: int, status: RoutineStatus) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE routines SET status = ? WHERE id = ?", (status, routine_id))

    def delete(self, routine_id: int) -> bool:
        with self._lock, self._db:
            return self._db.execute("DELETE FROM routines WHERE id = ?", (routine_id,)).rowcount > 0

    def record_run(
        self,
        routine_id: int,
        trigger: str,
        conditions: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        result: RunResult,
        *,
        started_at: float | None = None,
        dry_run: bool = False,
    ) -> RoutineRun:
        started_at = time.time() if started_at is None else started_at
        with self._lock, self._db:
            cursor = self._db.execute(
                "INSERT INTO routine_runs (routine_id, started_at, trigger, conditions, actions, result, "
                "dry_run) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    routine_id,
                    started_at,
                    trigger,
                    json.dumps(conditions, ensure_ascii=False),
                    json.dumps(actions, ensure_ascii=False),
                    result,
                    int(dry_run),
                ),
            )
            if result in EXECUTED:
                self._db.execute("UPDATE routines SET last_run_at = ? WHERE id = ?", (started_at, routine_id))
            self._db.execute(
                "DELETE FROM routine_runs WHERE routine_id = ? AND id NOT IN (SELECT id FROM routine_runs "
                "WHERE routine_id = ? ORDER BY started_at DESC, id DESC LIMIT ?)",
                (routine_id, routine_id, KEEP_RUNS),
            )
        return RoutineRun(
            int(cursor.lastrowid or 0), routine_id, started_at, trigger, conditions, actions, result, dry_run
        )

    def runs(self, routine_id: int | None = None, limit: int = 50) -> list[RoutineRun]:
        """The newest runs first, of one routine or all."""
        query = "SELECT * FROM routine_runs"
        values: list[object] = []
        if routine_id is not None:
            query += " WHERE routine_id = ?"
            values.append(routine_id)
        query += " ORDER BY started_at DESC, id DESC LIMIT ?"
        values.append(limit)
        with self._lock:
            rows = self._db.execute(query, values).fetchall()
        return [_run(row) for row in rows]

    def executed_since(self, routine_id: int, since: float) -> int:
        """How often the routine really acted since a point in time."""
        marks = ", ".join("?" for _ in EXECUTED)
        with self._lock:
            row = self._db.execute(
                f"SELECT COUNT(*) FROM routine_runs WHERE routine_id = ? AND started_at >= ? "  # noqa: S608
                f"AND dry_run = 0 AND result IN ({marks})",
                (routine_id, since, *EXECUTED),
            ).fetchone()
        return int(row[0])


def _routine(row: sqlite3.Row) -> Routine:
    return Routine(
        id=row["id"],
        person_id=row["person_id"],
        name=row["name"],
        text=row["text"],
        trigger=json.loads(row["trigger"]),
        conditions=json.loads(row["conditions"]),
        actions=json.loads(row["actions"]),
        report=bool(row["report"]),
        status=row["status"],
        needs_owner=bool(row["needs_owner"]),
        confirmed_at=row["confirmed_at"],
        approved_by=row["approved_by"],
        cooldown_minutes=int(row["cooldown_minutes"]),
        daily_limit=int(row["daily_limit"]),
        created_at=row["created_at"],
        last_run_at=row["last_run_at"],
    )


def _run(row: sqlite3.Row) -> RoutineRun:
    return RoutineRun(
        id=row["id"],
        routine_id=row["routine_id"],
        started_at=row["started_at"],
        trigger=row["trigger"],
        conditions=json.loads(row["conditions"]),
        actions=json.loads(row["actions"]),
        result=row["result"],
        dry_run=bool(row["dry_run"]),
    )


_books: weakref.WeakKeyDictionary[Store, RoutineBook] = weakref.WeakKeyDictionary()
_books_lock = threading.Lock()


def routine_book(store: Store) -> RoutineBook:
    """The routine tables of this database, created on first use."""
    with _books_lock:
        book = _books.get(store)
        if book is None:
            book = _books[store] = RoutineBook(store)
        return book
