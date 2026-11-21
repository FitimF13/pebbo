"""Paired phones: pairing with a code, the phone's token and the app API.

1. The owner creates a pairing for a person in the control centre. The core shows a
   six-digit code and a QR code with its address on the home network and the code.
2. The phone sends the code once to ``POST /api/app/pair`` and gets its own token, bound to
   that person. Only a hash of the token is stored.
3. Every other ``/api/app/`` route needs ``Authorization: Bearer <token>``. The token is
   checked on every request, so removing a phone in the control centre takes effect at once.

The app API answers from the home network (see ``pebbo.access``), the control centre routes
only on this computer. Details: docs/phone.md.
"""

# No "from __future__ import annotations": FastAPI must see the local Session dependency type.
import hashlib
import ipaddress
import os
import secrets
import socket
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from pebbo import __version__, clock
from pebbo.chat import ChatUnavailable, TextChat
from pebbo.config import ServerConfig
from pebbo.control_api import MemoryOut, ReminderOut, _memory, _reminder
from pebbo.store import Person, Phone, Reminder, Role, Store

PAIRING_SECONDS = 10 * 60
# Wrong codes in a row after which every open pairing ends.
MAX_FAILED_ATTEMPTS = 5
# How often the last-seen time of a phone is written at most.
_TOUCH_SECONDS = 30.0
NOT_PAIRED = "Dieses Handy ist nicht mehr gekoppelt."


def token_hash(secret: str) -> str:
    """Tokens and codes are stored only as hashes. Tokens are random, so a fast hash is enough."""
    return hashlib.sha256(secret.encode()).hexdigest()


def _new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _private(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.is_private and not (ip.is_loopback or ip.is_link_local or ip.is_unspecified)


def _preference(address: str) -> tuple[int, str]:
    # Home routers mostly use 192.168.x.x. 172.16/12 is often a virtual network of Docker or WSL.
    order = ("192.168.", "10.", "172.")
    return next((i for i, prefix in enumerate(order) if address.startswith(prefix)), len(order)), address


def local_addresses() -> list[str]:
    """This computer's IPv4 addresses on the home network, most likely first. Sends nothing."""
    found: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(str(info[4][0]))
    except OSError:
        pass
    try:
        # Connecting a UDP socket only picks the outgoing interface, no packet is sent.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.254.254.254", 9))
            found.add(str(probe.getsockname()[0]))
    except OSError:
        pass
    return sorted((address for address in found if _private(address)), key=_preference)


def app_addresses(config: ServerConfig) -> tuple[list[str], bool]:
    """The addresses a phone can use to reach the core, and whether the core listens on the network."""
    configured = os.environ.get("PEBBO_APP_ADDRESS", "").strip().rstrip("/")
    if configured:
        return [configured], True
    host = config.host.strip("[]")
    reachable = host in ("0.0.0.0", "::") or _private(host)  # noqa: S104 - comparing, not binding
    hosts = [host] if _private(host) else local_addresses()
    return [f"http://{address}:{config.port}" for address in hosts], reachable


# Control centre -----------------------------------------------------------


class PairingIn(BaseModel):
    person_id: int


class PairingOut(BaseModel):
    id: int
    person_id: int
    expires_at: float


class NewPairingOut(PairingOut):
    code: str
    # Where the phone reaches this core, most likely first. The QR code uses one of them.
    addresses: list[str]
    # False when the core only listens on this computer, so phones cannot reach it.
    reachable: bool


class PhoneOut(BaseModel):
    id: int
    person_id: int
    name: str
    created_at: float
    last_seen_at: float | None


class PhonesOut(BaseModel):
    phones: list[PhoneOut]
    pairings: list[PairingOut]


def _phone(phone: Phone) -> PhoneOut:
    return PhoneOut(
        id=phone.id,
        person_id=phone.person_id,
        name=phone.name,
        created_at=phone.created_at,
        last_seen_at=phone.last_seen_at,
    )


def phone_control_router(store: Store, chat: TextChat | None = None) -> APIRouter:
    """Pairing and removing phones, for the control centre on this computer."""
    router = APIRouter(prefix="/api/control/phones")

    @router.get("")
    def phones() -> PhonesOut:
        return PhonesOut(
            phones=[_phone(phone) for phone in store.phones()],
            pairings=[
                PairingOut(id=p.id, person_id=p.person_id, expires_at=p.expires_at)
                for p in store.phone_pairings()
            ],
        )

    @router.post("/pairings", status_code=201)
    def create_pairing(body: PairingIn) -> NewPairingOut:
        if store.person(body.person_id) is None:
            raise HTTPException(404, "Diese Person gibt es nicht.")
        taken = store.open_code_hashes()
        code = _new_code()
        while token_hash(code) in taken:
            code = _new_code()
        pairing = store.create_phone_pairing(body.person_id, token_hash(code), time.time() + PAIRING_SECONDS)
        addresses, reachable = app_addresses(ServerConfig())
        return NewPairingOut(
            id=pairing.id,
            person_id=pairing.person_id,
            expires_at=pairing.expires_at,
            code=code,
            addresses=addresses,
            reachable=reachable,
        )

    @router.delete("/pairings/{pairing_id}", status_code=204)
    def cancel_pairing(pairing_id: int) -> None:
        if not store.cancel_phone_pairing(pairing_id):
            raise HTTPException(404, "Diese Kopplung ist nicht mehr offen.")

    @router.delete("/{phone_id}", status_code=204)
    def remove_phone(phone_id: int) -> None:
        if not store.remove_phone(phone_id):
            raise HTTPException(404, "Dieses Handy gibt es nicht.")
        if chat is not None:
            chat.forget(phone_id)
        logger.info("Phone {} removed", phone_id)

    return router


# App API --------------------------------------------------------------------


@dataclass(frozen=True)
class AppSession:
    """Who a request of the app comes from."""

    phone: Phone
    person: Person


class PairIn(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    name: str = Field(default="Handy", max_length=40)


class PersonInfo(BaseModel):
    id: int
    name: str
    role: Role


class PhoneInfo(BaseModel):
    id: int
    name: str


class PairOut(BaseModel):
    token: str
    phone: PhoneInfo
    person: PersonInfo


class MeOut(BaseModel):
    person: PersonInfo
    phone: PhoneInfo
    version: str


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class ChatOut(BaseModel):
    answer: str
    emotion: str
    actions: list[str]


class NotificationOut(BaseModel):
    id: int
    kind: Literal["reminder"]
    text: str
    due_at: float
    due_text: str


class AcknowledgeIn(BaseModel):
    # Everything due up to this time was shown.
    until: float


def _person_info(person: Person) -> PersonInfo:
    return PersonInfo(id=person.id, name=person.name, role=person.role)


def _notification(reminder: Reminder) -> NotificationOut:
    due = datetime.fromtimestamp(reminder.due_at, clock.timezone())
    return NotificationOut(
        id=reminder.id,
        kind="reminder",
        text=reminder.text,
        due_at=reminder.due_at,
        due_text=clock.spoken_datetime(due),
    )


def _bearer(value: str) -> str:
    scheme, _, token = value.partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


def app_router(store: Store, chat: TextChat | None = None) -> APIRouter:
    """The API of the phone app. Everything except pairing acts for the phone's person only."""
    router = APIRouter(prefix="/api/app")

    def session(authorization: Annotated[str, Header()] = "") -> AppSession:
        phone = store.phone_by_token_hash(token_hash(_bearer(authorization))) if authorization else None
        person = store.person(phone.person_id) if phone is not None else None
        if phone is None or person is None:
            raise HTTPException(401, NOT_PAIRED, headers={"WWW-Authenticate": "Bearer"})
        now = time.time()
        if phone.last_seen_at is None or now - phone.last_seen_at > _TOUCH_SECONDS:
            store.touch_phone(phone.id, now)
        return AppSession(phone, person)

    Session = Annotated[AppSession, Depends(session)]

    @router.post("/pair")
    def pair(body: PairIn) -> PairOut:
        token = secrets.token_urlsafe(32)
        phone = store.redeem_phone_pairing(
            token_hash(body.code), body.name, token_hash(token), MAX_FAILED_ATTEMPTS
        )
        person = store.person(phone.person_id) if phone is not None else None
        if phone is None or person is None:
            raise HTTPException(
                404, "Dieser Code stimmt nicht oder ist abgelaufen. Erstelle im Kontrollzentrum einen neuen."
            )
        logger.info("Phone {} paired", phone.id)
        return PairOut(
            token=token, phone=PhoneInfo(id=phone.id, name=phone.name), person=_person_info(person)
        )

    @router.get("/me")
    def me(current: Session) -> MeOut:
        return MeOut(
            person=_person_info(current.person),
            phone=PhoneInfo(id=current.phone.id, name=current.phone.name),
            version=__version__,
        )

    @router.delete("/me", status_code=204)
    def unpair(current: Session) -> None:
        store.remove_phone(current.phone.id)
        if chat is not None:
            chat.forget(current.phone.id)
        logger.info("Phone {} unpaired itself", current.phone.id)

    @router.get("/reminders")
    def reminders(current: Session) -> list[ReminderOut]:
        return [_reminder(reminder) for reminder in store.reminders(current.person.id)]

    @router.delete("/reminders/{reminder_id}", status_code=204)
    def cancel_reminder(reminder_id: int, current: Session) -> None:
        reminder = store.reminder_by_id(reminder_id)
        if reminder is None or reminder.person_id != current.person.id:
            raise HTTPException(404, "Diese Erinnerung gibt es nicht.")
        if not store.cancel_reminder(reminder_id):
            raise HTTPException(404, "Diese Erinnerung ist nicht mehr offen.")

    @router.get("/memories")
    def memories(current: Session) -> list[MemoryOut]:
        return [_memory(memory) for memory in store.memories(current.person.id)]

    @router.delete("/memories/{memory_id}", status_code=204)
    def delete_memory(memory_id: int, current: Session) -> None:
        memory = store.memory_by_id(memory_id)
        if memory is None or memory.person_id != current.person.id:
            raise HTTPException(404, "Diesen Eintrag gibt es nicht.")
        store.delete_memory(memory_id)

    @router.post("/chat")
    async def chat_message(body: ChatIn, current: Session) -> ChatOut:
        if chat is None:
            raise HTTPException(503, "Der Chat ist auf diesem Pebbo nicht eingerichtet.")
        try:
            reply = await chat.reply(current.phone.id, current.person, body.text.strip())
        except ChatUnavailable as error:
            raise HTTPException(503, "Pebbo kann gerade nicht nachdenken. Läuft Ollama?") from error
        return ChatOut(answer=reply.answer, emotion=reply.emotion, actions=reply.actions)

    @router.get("/notifications")
    def notifications(current: Session) -> list[NotificationOut]:
        return [_notification(reminder) for reminder in store.phone_notifications(current.phone)]

    @router.post("/notifications/ack", status_code=204)
    def acknowledge(body: AcknowledgeIn, current: Session) -> None:
        store.acknowledge_phone_notifications(current.phone.id, min(body.until, time.time()))

    return router
