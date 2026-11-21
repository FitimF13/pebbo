"""Local SQLite storage for people, voices, memories and reminders.

Each Pebbo instance has exactly one database file. It never leaves the machine. Voice
fingerprints are stored as numeric embeddings, never as recordings.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Literal

import numpy as np

# How alike a misheard name must be to a household member's name (0 to 1).
SIMILAR_NAME = 0.75

Role = Literal["owner", "adult", "child", "colleague"]
MemoryKind = Literal["fact", "preference", "summary"]
ROLES: tuple[Role, ...] = ("owner", "adult", "child", "colleague")

SCHEMA = """
CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('owner', 'adult', 'child', 'colleague')),
    voice_enabled INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS voiceprints (
    person_id INTEGER PRIMARY KEY REFERENCES people(id) ON DELETE CASCADE,
    embedding BLOB NOT NULL,
    samples INTEGER NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS voice_claims (
    id INTEGER PRIMARY KEY,
    claimed_name TEXT NOT NULL,
    person_id INTEGER REFERENCES people(id) ON DELETE CASCADE,
    embedding BLOB NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY,
    person_id INTEGER REFERENCES people(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('fact', 'preference', 'summary')),
    text TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    due_at REAL NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'delivered', 'cancelled')),
    created_at REAL NOT NULL,
    delivered_at REAL
);
CREATE INDEX IF NOT EXISTS reminders_due ON reminders (status, due_at);
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY,
    device_id TEXT NOT NULL,
    client_id TEXT NOT NULL,
    name TEXT NOT NULL,
    board TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'paired')),
    pairing_code TEXT,
    code_expires_at REAL,
    token TEXT,
    created_at REAL NOT NULL,
    last_seen_at REAL,
    UNIQUE (device_id, client_id)
);
"""


@dataclass(frozen=True)
class Person:
    id: int
    name: str
    role: Role
    voice_enabled: bool
    voice_samples: int


@dataclass(frozen=True)
class Memory:
    id: int
    person_id: int | None
    kind: MemoryKind
    text: str
    source: str
    created_at: float


@dataclass(frozen=True)
class Reminder:
    id: int
    person_id: int
    text: str
    due_at: float
    status: str
    created_at: float


@dataclass(frozen=True)
class VoiceClaim:
    id: int
    claimed_name: str
    person_id: int | None
    created_at: float


@dataclass(frozen=True)
class Device:
    """A Pebbo body. It pairs once with a code shown on its screen and then gets its own token."""

    id: int
    device_id: str
    client_id: str
    name: str
    board: str
    status: str
    pairing_code: str | None
    code_expires_at: float | None
    token: str | None
    created_at: float
    last_seen_at: float | None


def default_data_dir() -> Path:
    """Where Pebbo keeps its database and downloaded models, outside the repository."""
    configured = os.environ.get("PEBBO_DATA_DIR")
    if configured:
        return Path(configured)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Pebbo"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "pebbo"


def _vector(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


class Store:
    """Thread-safe access to the instance database."""

    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute("PRAGMA foreign_keys = ON")
            self._db.executescript(SCHEMA)
            self._db.executescript(INTEGRATIONS_SCHEMA)
            self._db.executescript(PHONE_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # People ---------------------------------------------------------------

    def add_person(self, name: str, role: Role) -> Person:
        name = name.strip()
        if not name:
            raise ValueError("A person needs a name.")
        if role not in ROLES:
            raise ValueError(f"Unknown role {role!r}.")
        with self._lock, self._db:
            if role == "owner" and self._db.execute("SELECT 1 FROM people WHERE role = 'owner'").fetchone():
                raise ValueError("This Pebbo already has an owner.")
            cursor = self._db.execute(
                "INSERT INTO people (name, role, created_at) VALUES (?, ?, ?)", (name, role, time.time())
            )
        person = self.person(int(cursor.lastrowid or 0))
        if person is None:
            raise RuntimeError("The new person could not be read back.")
        return person

    def people(self) -> list[Person]:
        with self._lock:
            rows = self._db.execute(
                "SELECT p.*, COALESCE(v.samples, 0) AS samples FROM people p "
                "LEFT JOIN voiceprints v ON v.person_id = p.id ORDER BY p.id"
            ).fetchall()
        return [self._person(row) for row in rows]

    def person(self, person_id: int) -> Person | None:
        with self._lock:
            row = self._db.execute(
                "SELECT p.*, COALESCE(v.samples, 0) AS samples FROM people p "
                "LEFT JOIN voiceprints v ON v.person_id = p.id WHERE p.id = ?",
                (person_id,),
            ).fetchone()
        return self._person(row) if row else None

    def find_person(self, name: str) -> Person | None:
        wanted = name.strip().lower()
        return next((person for person in self.people() if person.name.lower() == wanted), None)

    def find_similar_person(self, name: str) -> Person | None:
        """Find a person whose name sounds like ``name``, for names misheard by speech recognition."""
        exact = self.find_person(name)
        if exact or len(name.strip()) < 3:
            return exact
        wanted = name.strip().lower()
        scored = [(SequenceMatcher(None, wanted, p.name.lower()).ratio(), p) for p in self.people()]
        score, person = max(scored, key=lambda pair: pair[0], default=(0.0, None))
        return person if score >= SIMILAR_NAME else None

    def update_person(
        self, person_id: int, *, name: str | None = None, voice_enabled: bool | None = None
    ) -> None:
        with self._lock, self._db:
            if name is not None and name.strip():
                self._db.execute("UPDATE people SET name = ? WHERE id = ?", (name.strip(), person_id))
            if voice_enabled is not None:
                self._db.execute(
                    "UPDATE people SET voice_enabled = ? WHERE id = ?", (int(voice_enabled), person_id)
                )
                if not voice_enabled:
                    self._db.execute("DELETE FROM voiceprints WHERE person_id = ?", (person_id,))

    def remove_person(self, person_id: int) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM people WHERE id = ?", (person_id,))

    @staticmethod
    def _person(row: sqlite3.Row) -> Person:
        return Person(row["id"], row["name"], row["role"], bool(row["voice_enabled"]), int(row["samples"]))

    # Voices ---------------------------------------------------------------

    def voiceprints(self) -> dict[int, tuple[np.ndarray, int]]:
        """Return the voice fingerprint and sample count of every person with voice recognition on."""
        with self._lock:
            rows = self._db.execute(
                "SELECT v.person_id, v.embedding, v.samples FROM voiceprints v "
                "JOIN people p ON p.id = v.person_id WHERE p.voice_enabled = 1"
            ).fetchall()
        return {row["person_id"]: (_vector(row["embedding"]), int(row["samples"])) for row in rows}

    def save_voiceprint(self, person_id: int, embedding: np.ndarray, samples: int) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO voiceprints (person_id, embedding, samples, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(person_id) DO UPDATE SET embedding = excluded.embedding, "
                "samples = excluded.samples, updated_at = excluded.updated_at",
                (person_id, embedding.astype(np.float32).tobytes(), samples, time.time()),
            )

    def reset_voice(self, person_id: int) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM voiceprints WHERE person_id = ?", (person_id,))

    def add_voice_claim(self, claimed_name: str, embedding: np.ndarray) -> VoiceClaim:
        person = self.find_similar_person(claimed_name)
        with self._lock, self._db:
            cursor = self._db.execute(
                "INSERT INTO voice_claims (claimed_name, person_id, embedding, created_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    claimed_name.strip(),
                    person.id if person else None,
                    embedding.astype(np.float32).tobytes(),
                    time.time(),
                ),
            )
        return VoiceClaim(
            int(cursor.lastrowid or 0), claimed_name.strip(), person.id if person else None, time.time()
        )

    def voice_claims(self) -> list[VoiceClaim]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM voice_claims ORDER BY id").fetchall()
        return [
            VoiceClaim(row["id"], row["claimed_name"], row["person_id"], row["created_at"]) for row in rows
        ]

    def take_voice_claim(self, claim_id: int) -> tuple[VoiceClaim, np.ndarray] | None:
        """Remove a claim and return it with its embedding."""
        with self._lock, self._db:
            row = self._db.execute("SELECT * FROM voice_claims WHERE id = ?", (claim_id,)).fetchone()
            if not row:
                return None
            self._db.execute("DELETE FROM voice_claims WHERE id = ?", (claim_id,))
        claim = VoiceClaim(row["id"], row["claimed_name"], row["person_id"], row["created_at"])
        return claim, _vector(row["embedding"]).copy()

    # Memories -------------------------------------------------------------

    def add_memory(self, person_id: int | None, kind: MemoryKind, text: str, source: str = "said") -> Memory:
        text = " ".join(text.split())
        if not text:
            raise ValueError("A memory needs text.")
        now = time.time()
        with self._lock, self._db:
            cursor = self._db.execute(
                "INSERT INTO memories (person_id, kind, text, source, created_at) VALUES (?, ?, ?, ?, ?)",
                (person_id, kind, text, source, now),
            )
        return Memory(int(cursor.lastrowid or 0), person_id, kind, text, source, now)

    def memories(
        self, person_id: int | None = None, *, kind: MemoryKind | None = None, limit: int = 200
    ) -> list[Memory]:
        """Memories of one person (``None`` means household memories), newest first."""
        query = "SELECT * FROM memories WHERE person_id IS ?"
        values: list[object] = [person_id]
        if kind:
            query += " AND kind = ?"
            values.append(kind)
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        values.append(limit)
        with self._lock:
            rows = self._db.execute(query, values).fetchall()
        return [self._memory(row) for row in rows]

    def all_memories(self) -> list[Memory]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM memories ORDER BY created_at DESC, id DESC").fetchall()
        return [self._memory(row) for row in rows]

    def update_memory(self, memory_id: int, text: str) -> None:
        text = " ".join(text.split())
        if not text:
            raise ValueError("A memory needs text.")
        with self._lock, self._db:
            self._db.execute("UPDATE memories SET text = ? WHERE id = ?", (text, memory_id))

    def delete_memory(self, memory_id: int) -> bool:
        with self._lock, self._db:
            return self._db.execute("DELETE FROM memories WHERE id = ?", (memory_id,)).rowcount > 0

    def prune_summaries(self, person_id: int, keep: int = 20) -> None:
        with self._lock, self._db:
            self._db.execute(
                "DELETE FROM memories WHERE person_id = ? AND kind = 'summary' AND id NOT IN "
                "(SELECT id FROM memories WHERE person_id = ? AND kind = 'summary' "
                "ORDER BY created_at DESC LIMIT ?)",
                (person_id, person_id, keep),
            )

    @staticmethod
    def _memory(row: sqlite3.Row) -> Memory:
        return Memory(row["id"], row["person_id"], row["kind"], row["text"], row["source"], row["created_at"])

    # Reminders ------------------------------------------------------------

    def add_reminder(self, person_id: int, text: str, due_at: float) -> Reminder:
        text = " ".join(text.split())
        if not text:
            raise ValueError("A reminder needs text.")
        now = time.time()
        with self._lock, self._db:
            cursor = self._db.execute(
                "INSERT INTO reminders (person_id, text, due_at, status, created_at) "
                "VALUES (?, ?, ?, 'pending', ?)",
                (person_id, text, due_at, now),
            )
        return Reminder(int(cursor.lastrowid or 0), person_id, text, due_at, "pending", now)

    def reminders(self, person_id: int | None = None, *, pending_only: bool = True) -> list[Reminder]:
        query = "SELECT * FROM reminders WHERE 1 = 1"
        values: list[object] = []
        if person_id is not None:
            query += " AND person_id = ?"
            values.append(person_id)
        if pending_only:
            query += " AND status = 'pending'"
        query += " ORDER BY due_at"
        with self._lock:
            rows = self._db.execute(query, values).fetchall()
        return [self._reminder(row) for row in rows]

    def due_reminders(self, now: float) -> list[Reminder]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM reminders WHERE status = 'pending' AND due_at <= ? ORDER BY due_at", (now,)
            ).fetchall()
        return [self._reminder(row) for row in rows]

    def mark_delivered(self, reminder_id: int) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE reminders SET status = 'delivered', delivered_at = ? WHERE id = ?",
                (time.time(), reminder_id),
            )

    def cancel_reminder(self, reminder_id: int) -> bool:
        with self._lock, self._db:
            return (
                self._db.execute(
                    "UPDATE reminders SET status = 'cancelled' WHERE id = ? AND status = 'pending'",
                    (reminder_id,),
                ).rowcount
                > 0
            )

    @staticmethod
    def _reminder(row: sqlite3.Row) -> Reminder:
        return Reminder(
            row["id"], row["person_id"], row["text"], row["due_at"], row["status"], row["created_at"]
        )

    # Devices --------------------------------------------------------------

    def device(self, device_id: str, client_id: str) -> Device | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM devices WHERE device_id = ? AND client_id = ?", (device_id, client_id)
            ).fetchone()
        return self._device(row) if row else None

    def device_by_id(self, row_id: int) -> Device | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM devices WHERE id = ?", (row_id,)).fetchone()
        return self._device(row) if row else None

    def device_by_token(self, token: str) -> Device | None:
        if not token:
            return None
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM devices WHERE token = ? AND status = 'paired'", (token,)
            ).fetchone()
        return self._device(row) if row else None

    def devices(self) -> list[Device]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM devices ORDER BY id").fetchall()
        return [self._device(row) for row in rows]

    def request_pairing(
        self, device_id: str, client_id: str, board: str, code: str, expires_at: float
    ) -> Device:
        """Register an unpaired device, or give a known pending device a fresh pairing code."""
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO devices (device_id, client_id, name, board, status, pairing_code, "
                "code_expires_at, "
                "created_at) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?) "
                "ON CONFLICT (device_id, client_id) DO UPDATE SET pairing_code = excluded.pairing_code, "
                "code_expires_at = excluded.code_expires_at, board = excluded.board "
                "WHERE devices.status = 'pending'",
                (device_id, client_id, "Pebbo", board, code, expires_at, time.time()),
            )
        device = self.device(device_id, client_id)
        if device is None:
            raise RuntimeError("The device could not be read back.")
        return device

    def pair_device(self, code: str, token: str, now: float | None = None) -> Device | None:
        """Pair the pending device that shows this code, if the code is still valid."""
        now = time.time() if now is None else now
        with self._lock, self._db:
            row = self._db.execute(
                "SELECT id FROM devices WHERE status = 'pending' AND pairing_code = ? "
                "AND code_expires_at > ?",
                (code.strip(), now),
            ).fetchone()
            if row is None:
                return None
            self._db.execute(
                "UPDATE devices SET status = 'paired', token = ?, pairing_code = NULL, "
                "code_expires_at = NULL "
                "WHERE id = ?",
                (token, row["id"]),
            )
        return self.device_by_id(int(row["id"]))

    def rename_device(self, row_id: int, name: str) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE devices SET name = ? WHERE id = ?", (name.strip(), row_id))

    def touch_device(self, row_id: int) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE devices SET last_seen_at = ? WHERE id = ?", (time.time(), row_id))

    def remove_device(self, row_id: int) -> bool:
        with self._lock, self._db:
            return self._db.execute("DELETE FROM devices WHERE id = ?", (row_id,)).rowcount > 0

    @staticmethod
    def _device(row: sqlite3.Row) -> Device:
        return Device(
            row["id"],
            row["device_id"],
            row["client_id"],
            row["name"],
            row["board"],
            row["status"],
            row["pairing_code"],
            row["code_expires_at"],
            row["token"],
            row["created_at"],
            row["last_seen_at"],
        )

    # Feature modules ------------------------------------------------------

    def extension(self, schema: str) -> tuple[sqlite3.Connection, threading.Lock]:
        """Create the tables of a feature module and share this database with it.

        Routines and calendars keep their own tables in the same file (see
        ``pebbo.routines.storage`` and ``pebbo.calendars.storage``). They use the returned
        connection only while holding the returned lock.
        """
        with self._lock:
            self._db.executescript(schema)
        return self._db, self._lock

    # Integrations (MCP servers) -------------------------------------------

    def add_mcp_server(
        self,
        name: str,
        url: str,
        token: str,
        permission: IntegrationPermission = "household",
        *,
        enabled: bool = True,
        allow_public: bool = False,
    ) -> McpServer:
        with self._lock, self._db:
            cursor = self._db.execute(
                "INSERT INTO mcp_servers (name, url, token, permission, enabled, allow_public, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name.strip(), url.strip(), token, permission, int(enabled), int(allow_public), time.time()),
            )
        server = self.mcp_server(int(cursor.lastrowid or 0))
        if server is None:
            raise RuntimeError("The integration could not be read back.")
        return server

    def mcp_server(self, server_id: int) -> McpServer | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM mcp_servers WHERE id = ?", (server_id,)).fetchone()
        return self._mcp_server(row) if row else None

    def mcp_servers(self) -> list[McpServer]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM mcp_servers ORDER BY id").fetchall()
        return [self._mcp_server(row) for row in rows]

    def update_mcp_server(
        self,
        server_id: int,
        *,
        name: str | None = None,
        url: str | None = None,
        token: str | None = None,
        permission: IntegrationPermission | None = None,
        enabled: bool | None = None,
        allow_public: bool | None = None,
    ) -> None:
        """Change the given fields. A ``token`` of ``None`` keeps the stored one."""
        changes: dict[str, object] = {
            "name": name.strip() if name is not None else None,
            "url": url.strip() if url is not None else None,
            "token": token,
            "permission": permission,
            "enabled": int(enabled) if enabled is not None else None,
            "allow_public": int(allow_public) if allow_public is not None else None,
        }
        changes = {column: value for column, value in changes.items() if value is not None}
        if not changes:
            return
        assignments = ", ".join(f"{column} = ?" for column in changes)
        with self._lock, self._db:
            self._db.execute(
                f"UPDATE mcp_servers SET {assignments} WHERE id = ?",  # noqa: S608 (fixed column names)
                (*changes.values(), server_id),
            )

    def remove_mcp_server(self, server_id: int) -> bool:
        with self._lock, self._db:
            return self._db.execute("DELETE FROM mcp_servers WHERE id = ?", (server_id,)).rowcount > 0

    @staticmethod
    def _mcp_server(row: sqlite3.Row) -> McpServer:
        return McpServer(
            id=row["id"],
            name=row["name"],
            url=row["url"],
            token=row["token"],
            permission=row["permission"],
            enabled=bool(row["enabled"]),
            allow_public=bool(row["allow_public"]),
            created_at=row["created_at"],
        )

    # Phones ---------------------------------------------------------------
    #
    # A phone pairs once with a short-lived code that the owner creates for a person in the
    # control centre, and then gets its own token bound to that person. Only hashes of codes
    # and tokens are stored, so a copy of the database does not let anyone act as a phone.

    def create_phone_pairing(
        self, person_id: int, code_hash: str, expires_at: float, now: float | None = None
    ) -> PhonePairing:
        """Open a pairing for a person. An earlier open pairing of the same person ends."""
        now = time.time() if now is None else now
        with self._lock, self._db:
            self._db.execute(
                "DELETE FROM phone_pairings WHERE person_id = ? OR expires_at <= ?", (person_id, now)
            )
            cursor = self._db.execute(
                "INSERT INTO phone_pairings (person_id, code_hash, expires_at, created_at) "
                "VALUES (?, ?, ?, ?)",
                (person_id, code_hash, expires_at, now),
            )
        return PhonePairing(int(cursor.lastrowid or 0), person_id, expires_at, now)

    def phone_pairings(self, now: float | None = None) -> list[PhonePairing]:
        """The pairings that can still be used."""
        now = time.time() if now is None else now
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM phone_pairings WHERE expires_at > ? ORDER BY id", (now,)
            ).fetchall()
        return [PhonePairing(r["id"], r["person_id"], r["expires_at"], r["created_at"]) for r in rows]

    def open_code_hashes(self, now: float | None = None) -> set[str]:
        now = time.time() if now is None else now
        with self._lock:
            rows = self._db.execute(
                "SELECT code_hash FROM phone_pairings WHERE expires_at > ?", (now,)
            ).fetchall()
        return {str(row["code_hash"]) for row in rows}

    def cancel_phone_pairing(self, pairing_id: int) -> bool:
        with self._lock, self._db:
            return self._db.execute("DELETE FROM phone_pairings WHERE id = ?", (pairing_id,)).rowcount > 0

    def redeem_phone_pairing(
        self, code_hash: str, name: str, token_hash: str, max_failed: int, now: float | None = None
    ) -> Phone | None:
        """Exchange a pairing code once for a phone with its own token.

        A wrong code counts against every open pairing, and pairings with too many wrong
        attempts end, so the six digits cannot be guessed.
        """
        now = time.time() if now is None else now
        with self._lock, self._db:
            row = self._db.execute(
                "SELECT * FROM phone_pairings WHERE code_hash = ? AND expires_at > ?", (code_hash, now)
            ).fetchone()
            if row is None:
                self._db.execute(
                    "UPDATE phone_pairings SET failed_attempts = failed_attempts + 1 WHERE expires_at > ?",
                    (now,),
                )
                self._db.execute(
                    "DELETE FROM phone_pairings WHERE failed_attempts >= ? OR expires_at <= ?",
                    (max_failed, now),
                )
                return None
            self._db.execute("DELETE FROM phone_pairings WHERE id = ?", (row["id"],))
            cursor = self._db.execute(
                "INSERT INTO phones (person_id, name, token_hash, created_at, notified_until) "
                "VALUES (?, ?, ?, ?, ?)",
                (row["person_id"], name.strip() or "Handy", token_hash, now, now),
            )
            phone = self._db.execute("SELECT * FROM phones WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return self._phone(phone)

    def phone_by_token_hash(self, token_hash: str) -> Phone | None:
        if not token_hash:
            return None
        with self._lock:
            row = self._db.execute("SELECT * FROM phones WHERE token_hash = ?", (token_hash,)).fetchone()
        return self._phone(row) if row else None

    def phones(self) -> list[Phone]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM phones ORDER BY id").fetchall()
        return [self._phone(row) for row in rows]

    def touch_phone(self, phone_id: int, now: float | None = None) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE phones SET last_seen_at = ? WHERE id = ?",
                (time.time() if now is None else now, phone_id),
            )

    def remove_phone(self, phone_id: int) -> bool:
        with self._lock, self._db:
            return self._db.execute("DELETE FROM phones WHERE id = ?", (phone_id,)).rowcount > 0

    def phone_notifications(self, phone: Phone, now: float | None = None) -> list[Reminder]:
        """The person's reminders that became due since the phone last acknowledged them."""
        now = time.time() if now is None else now
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM reminders WHERE person_id = ? AND status != 'cancelled' "
                "AND due_at > ? AND due_at <= ? ORDER BY due_at",
                (phone.person_id, phone.notified_until, now),
            ).fetchall()
        return [self._reminder(row) for row in rows]

    def acknowledge_phone_notifications(self, phone_id: int, until: float) -> None:
        """Mark the person's due reminders up to ``until`` as seen on this phone and as delivered."""
        with self._lock, self._db:
            row = self._db.execute("SELECT person_id FROM phones WHERE id = ?", (phone_id,)).fetchone()
            if row is None:
                return
            self._db.execute(
                "UPDATE phones SET notified_until = MAX(notified_until, ?) WHERE id = ?", (until, phone_id)
            )
            self._db.execute(
                "UPDATE reminders SET status = 'delivered', delivered_at = ? "
                "WHERE person_id = ? AND status = 'pending' AND due_at <= ?",
                (time.time(), row["person_id"], until),
            )

    def memory_by_id(self, memory_id: int) -> Memory | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        return self._memory(row) if row else None

    def reminder_by_id(self, reminder_id: int) -> Reminder | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
        return self._reminder(row) if row else None

    @staticmethod
    def _phone(row: sqlite3.Row) -> Phone:
        return Phone(
            row["id"],
            row["person_id"],
            row["name"],
            row["created_at"],
            row["last_seen_at"],
            row["notified_until"],
        )


# Who may use an integration's tools: everyone (also guests), household members, or the owner.
IntegrationPermission = Literal["everyone", "household", "owner"]

INTEGRATIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS mcp_servers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    url TEXT NOT NULL,
    token TEXT NOT NULL DEFAULT '',
    permission TEXT NOT NULL DEFAULT 'household' CHECK (permission IN ('everyone', 'household', 'owner')),
    enabled INTEGER NOT NULL DEFAULT 1,
    allow_public INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
"""


@dataclass(frozen=True)
class McpServer:
    """An MCP server the owner added in the control centre, for example Home Assistant.

    The access token is only read by the core to connect. The control centre API never returns it.
    """

    id: int
    name: str
    url: str
    token: str = field(repr=False)
    permission: IntegrationPermission
    enabled: bool
    allow_public: bool
    created_at: float


PHONE_SCHEMA = """
CREATE TABLE IF NOT EXISTS phone_pairings (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    code_hash TEXT NOT NULL,
    expires_at REAL NOT NULL,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS phones (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL,
    last_seen_at REAL,
    -- Due reminders up to this time were shown on the phone already.
    notified_until REAL NOT NULL
);
"""


@dataclass(frozen=True)
class PhonePairing:
    """An open invitation for a person's phone. The code itself is shown only once."""

    id: int
    person_id: int
    expires_at: float
    created_at: float


@dataclass(frozen=True)
class Phone:
    """A paired phone. It acts for exactly one person."""

    id: int
    person_id: int
    name: str
    created_at: float
    last_seen_at: float | None
    notified_until: float
