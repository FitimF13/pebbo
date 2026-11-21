"""Two Pebbos: a home and an office instance, each with its own data, joined by handoffs.

Instances pair once with a six-digit code, like bodies do. Each side then holds a token for
calling the other. The only thing one instance can send the other is a handoff that a person
prepared and the owner approved in the control centre; neither can read the other's data.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from loguru import logger

from pebbo.store import Store

INVITE_SECONDS = 10 * 60
_INSERT_PEER = (
    "INSERT INTO peers (name, address, outgoing_token, incoming_token_hash, created_at) "
    "VALUES (?, ?, ?, ?, ?)"
)
SCHEMA = """
CREATE TABLE IF NOT EXISTS peer_invites (
    code TEXT PRIMARY KEY,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS peers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    address TEXT NOT NULL,
    outgoing_token TEXT NOT NULL,
    incoming_token_hash TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS handoffs (
    id INTEGER PRIMARY KEY,
    peer_id INTEGER REFERENCES peers(id) ON DELETE SET NULL,
    peer_name TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('out', 'in')),
    person_name TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'sent', 'rejected', 'failed', 'received')),
    created_at REAL NOT NULL,
    decided_at REAL
);
"""

# Sends a JSON body to a peer: (url, body, token) -> parsed JSON reply. Replaced in tests.
Transport = Callable[[str, dict[str, Any], str], dict[str, Any]]


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def http_transport(url: str, body: dict[str, Any], token: str) -> dict[str, Any]:
    if not url.startswith(("http://", "https://")):
        raise ValueError("Only http and https addresses are allowed.")
    request = urllib.request.Request(  # noqa: S310 - the scheme is checked above
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - peer address checked
        reply: dict[str, Any] = json.loads(response.read() or b"{}")
        return reply


@dataclass(frozen=True)
class Peer:
    id: int
    name: str
    address: str
    created_at: float


@dataclass(frozen=True)
class Handoff:
    id: int
    peer_name: str
    direction: str
    person_name: str
    content: str
    status: str
    created_at: float
    decided_at: float | None


class PeerError(Exception):
    """Pairing or sending to another instance failed. The message is shown to the owner."""


# Wrong codes in a row before every open invitation is withdrawn, so six digits cannot be guessed.
MAX_FAILED_PAIRINGS = 5


class Peers:
    """Pairing with other instances and the handoffs between them, in the instance database."""

    def __init__(
        self, store: Store, name: str, own_address: str, transport: Transport = http_transport
    ) -> None:
        self.store = store
        self.name = name
        self.own_address = own_address.rstrip("/")
        self._transport = transport
        self._failed_attempts = 0
        with store._lock, store._db:
            store._db.executescript(SCHEMA)

    def _query(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self.store._lock:
            return list(self.store._db.execute(sql, params).fetchall())

    def _write(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        with self.store._lock, self.store._db:
            cursor = self.store._db.execute(sql, params)
            return int(cursor.lastrowid or 0)

    # Pairing --------------------------------------------------------------

    def invite(self, now: float | None = None) -> str:
        """A code the other instance enters to pair with this one."""
        now = time.time() if now is None else now
        code = f"{secrets.randbelow(1_000_000):06d}"
        self._write("DELETE FROM peer_invites WHERE expires_at < ?", (now,))
        self._write(
            "INSERT OR REPLACE INTO peer_invites (code, expires_at) VALUES (?, ?)",
            (code, now + INVITE_SECONDS),
        )
        return code

    def accept(
        self, code: str, name: str, address: str, token_for_them: str, now: float | None = None
    ) -> str:
        """The other instance pairs with our code. Returns the token it uses to call us."""
        now = time.time() if now is None else now
        rows = self._query(
            "SELECT code FROM peer_invites WHERE code = ? AND expires_at > ?", (code.strip(), now)
        )
        if not rows:
            self._failed_attempts += 1
            if self._failed_attempts >= MAX_FAILED_PAIRINGS:
                # Someone may be guessing: every open code becomes invalid, the owner makes a new one.
                self._write("DELETE FROM peer_invites")
                self._failed_attempts = 0
                logger.warning("Too many wrong pairing codes, open invitations were withdrawn")
            raise PeerError("Dieser Code ist ungültig oder abgelaufen.")
        self._failed_attempts = 0
        self._write("DELETE FROM peer_invites WHERE code = ?", (code.strip(),))
        token_for_us = secrets.token_urlsafe(32)
        self._write(
            _INSERT_PEER,
            (name.strip()[:40] or "Pebbo", address.rstrip("/"), token_for_them, _hash(token_for_us), now),
        )
        logger.info("Paired with another Pebbo instance")
        return token_for_us

    def connect(self, address: str, code: str) -> Peer:
        """Pair with the instance at ``address`` using the code it shows."""
        address = address.rstrip("/")
        token_for_them = secrets.token_urlsafe(32)
        try:
            reply = self._transport(
                f"{address}/api/peer/pair",
                {"code": code, "name": self.name, "address": self.own_address, "token": token_for_them},
                "",
            )
        except (OSError, urllib.error.URLError, ValueError) as error:
            raise PeerError("Die andere Instanz ist nicht erreichbar.") from error
        token_for_us, their_name = str(reply.get("token", "")), str(reply.get("name", "Pebbo"))
        if not token_for_us:
            raise PeerError(str(reply.get("detail", "Die Kopplung hat nicht geklappt.")))
        peer_id = self._write(
            _INSERT_PEER,
            (their_name[:40], address, token_for_us, _hash(token_for_them), time.time()),
        )
        peer = self.peer(peer_id)
        if peer is None:
            raise PeerError("Die Kopplung hat nicht geklappt.")
        return peer

    def peers(self) -> list[Peer]:
        return [
            Peer(r["id"], r["name"], r["address"], r["created_at"])
            for r in self._query("SELECT * FROM peers ORDER BY id")
        ]

    def peer(self, peer_id: int) -> Peer | None:
        rows = self._query("SELECT * FROM peers WHERE id = ?", (peer_id,))
        return (
            Peer(rows[0]["id"], rows[0]["name"], rows[0]["address"], rows[0]["created_at"]) if rows else None
        )

    def peer_by_token(self, token: str) -> Peer | None:
        rows = (
            self._query("SELECT * FROM peers WHERE incoming_token_hash = ?", (_hash(token),)) if token else []
        )
        return (
            Peer(rows[0]["id"], rows[0]["name"], rows[0]["address"], rows[0]["created_at"]) if rows else None
        )

    def remove(self, peer_id: int) -> bool:
        """Unpair at once: the other instance's token stops working."""
        with self.store._lock, self.store._db:
            return self.store._db.execute("DELETE FROM peers WHERE id = ?", (peer_id,)).rowcount > 0

    # Handoffs -------------------------------------------------------------

    def prepare(self, person_name: str, content: str, peer_name: str = "") -> Handoff:
        """A handoff that waits for the owner's approval."""
        peers = self.peers()
        if not peers:
            raise PeerError("Es ist noch keine zweite Pebbo-Instanz verbunden.")
        peer = next((p for p in peers if p.name.lower() == peer_name.strip().lower()), peers[0])
        handoff_id = self._write(
            "INSERT INTO handoffs (peer_id, peer_name, direction, person_name, content, status, created_at) "
            "VALUES (?, ?, 'out', ?, ?, 'pending', ?)",
            (peer.id, peer.name, person_name, content.strip()[:2000], time.time()),
        )
        handoff = self.handoff(handoff_id)
        if handoff is None:
            raise PeerError("Die Übergabe konnte nicht gespeichert werden.")
        return handoff

    def handoffs(self) -> list[Handoff]:
        return [self._handoff(r) for r in self._query("SELECT * FROM handoffs ORDER BY id DESC LIMIT 100")]

    def handoff(self, handoff_id: int) -> Handoff | None:
        rows = self._query("SELECT * FROM handoffs WHERE id = ?", (handoff_id,))
        return self._handoff(rows[0]) if rows else None

    def decide(self, handoff_id: int, approve: bool) -> Handoff:
        """Approve and send, or reject a pending handoff. Nothing leaves without approval."""
        rows = self._query(
            "SELECT * FROM handoffs WHERE id = ? AND status = 'pending' AND direction = 'out'", (handoff_id,)
        )
        if not rows:
            raise PeerError("Diese Übergabe wartet nicht mehr auf eine Freigabe.")
        row = rows[0]
        status = "rejected"
        if approve:
            peer_rows = self._query("SELECT * FROM peers WHERE id = ?", (row["peer_id"],))
            if not peer_rows:
                raise PeerError("Die andere Instanz ist nicht mehr verbunden.")
            peer = peer_rows[0]
            try:
                reply = self._transport(
                    f"{peer['address']}/api/peer/handoff",
                    {"from": self.name, "person": row["person_name"], "content": row["content"]},
                    peer["outgoing_token"],
                )
                # Only a confirmed receipt counts, not any answer.
                status = "sent" if reply.get("status") == "received" else "failed"
            except (OSError, urllib.error.URLError, ValueError) as error:
                logger.warning("Handoff could not be sent: {}", type(error).__name__)
                status = "failed"
        self._write(
            "UPDATE handoffs SET status = ?, decided_at = ? WHERE id = ?", (status, time.time(), handoff_id)
        )
        handoff = self.handoff(handoff_id)
        if handoff is None:
            raise PeerError("Die Übergabe ist verschwunden.")
        logger.info("Handoff {} {}", handoff_id, status)
        return handoff

    def receive(self, peer: Peer, person_name: str, content: str) -> Handoff:
        """A handoff from the other instance: logged, and delivered to the person as a reminder."""
        person = self.store.find_similar_person(person_name) if person_name else None
        handoff_id = self._write(
            "INSERT INTO handoffs (peer_id, peer_name, direction, person_name, content, status, created_at, "
            "decided_at) VALUES (?, ?, 'in', ?, ?, 'received', ?, ?)",
            (
                peer.id,
                peer.name,
                person.name if person else person_name,
                content.strip()[:2000],
                time.time(),
                time.time(),
            ),
        )
        if person is not None:
            # A reminder due now is spoken as soon as Pebbo can speak, or shown in the app.
            self.store.add_reminder(
                person.id, f"Übergabe von {peer.name}: {content.strip()[:500]}", time.time()
            )
        else:
            self.store.add_memory(
                None, "fact", f"Übergabe von {peer.name}: {content.strip()[:500]}", source="handoff"
            )
        handoff = self.handoff(handoff_id)
        if handoff is None:
            raise PeerError("Die Übergabe ist verschwunden.")
        logger.info("Handoff received from another Pebbo instance")
        return handoff

    @staticmethod
    def _handoff(row: sqlite3.Row) -> Handoff:
        return Handoff(
            row["id"], row["peer_name"], row["direction"], row["person_name"], row["content"], row["status"],
            row["created_at"], row["decided_at"],
        )  # fmt: skip
