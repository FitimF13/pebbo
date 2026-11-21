"""HTTP API of the web control centre: people, voices, memories and reminders.

The core listens only on the local machine in phase 2, so the API needs no sign-in yet.
Pairing and sign-in for other devices follow in phase 4.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from pebbo import clock
from pebbo.people.speaker import merged
from pebbo.store import Device, Memory, Person, Reminder, Role, Store, VoiceClaim


class PersonOut(BaseModel):
    id: int
    name: str
    role: Role
    voice_enabled: bool
    voice_samples: int


class PersonIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    role: Role


class PersonPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    voice_enabled: bool | None = None


class MemoryOut(BaseModel):
    id: int
    person_id: int | None
    kind: Literal["fact", "preference", "summary"]
    text: str
    # Where the memory comes from: "said" (asked to remember), "learned" (in passing),
    # "summary" (conversation summary) or "control" (added in the control centre).
    source: str
    created_at: float


class MemoryIn(BaseModel):
    person_id: int | None
    text: str = Field(min_length=1, max_length=500)


class MemoryPatch(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class ReminderOut(BaseModel):
    id: int
    person_id: int
    text: str
    due_at: float
    due_text: str


class VoiceClaimOut(BaseModel):
    id: int
    claimed_name: str
    person_id: int | None
    created_at: float


class ConfirmClaim(BaseModel):
    person_id: int


class DeviceOut(BaseModel):
    id: int
    name: str
    board: str
    status: Literal["pending", "paired"]
    online: bool
    last_seen_at: float | None


class PairDevice(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class DevicePatch(BaseModel):
    name: str = Field(min_length=1, max_length=40)


def _person(person: Person) -> PersonOut:
    return PersonOut(
        id=person.id,
        name=person.name,
        role=person.role,
        voice_enabled=person.voice_enabled,
        voice_samples=person.voice_samples,
    )


def _memory(memory: Memory) -> MemoryOut:
    return MemoryOut(
        id=memory.id,
        person_id=memory.person_id,
        kind=memory.kind,
        text=memory.text,
        source=memory.source,
        created_at=memory.created_at,
    )


def _reminder(reminder: Reminder) -> ReminderOut:
    due = datetime.fromtimestamp(reminder.due_at, clock.timezone())
    return ReminderOut(
        id=reminder.id,
        person_id=reminder.person_id,
        text=reminder.text,
        due_at=reminder.due_at,
        due_text=clock.spoken_datetime(due),
    )


def _claim(claim: VoiceClaim) -> VoiceClaimOut:
    return VoiceClaimOut(
        id=claim.id, claimed_name=claim.claimed_name, person_id=claim.person_id, created_at=claim.created_at
    )


def _device(device: Device) -> DeviceOut:
    from pebbo.devices.gateway import is_online

    return DeviceOut(
        id=device.id,
        name=device.name,
        board=device.board,
        status="paired" if device.status == "paired" else "pending",
        online=is_online(device.id),
        last_seen_at=device.last_seen_at,
    )


def control_router(store: Store) -> APIRouter:
    router = APIRouter(prefix="/api/control")

    def require_person(person_id: int) -> Person:
        person = store.person(person_id)
        if person is None:
            raise HTTPException(404, "Diese Person gibt es nicht.")
        return person

    @router.get("/people")
    def people() -> list[PersonOut]:
        return [_person(person) for person in store.people()]

    def check_name(name: str, person_id: int | None = None) -> None:
        # Names match voices, introductions and handoffs, so they must differ beyond case.
        if not name.strip():
            raise HTTPException(400, "Gib einen Namen ein.")
        if any(p.name.casefold() == name.strip().casefold() and p.id != person_id for p in store.people()):
            raise HTTPException(400, f"Es gibt schon jemanden namens {name.strip()}.")

    @router.post("/people", status_code=201)
    def add_person(body: PersonIn) -> PersonOut:
        people = store.people()
        if not people and body.role != "owner":
            raise HTTPException(400, "Die erste Person ist der Besitzer.")
        if body.role == "owner" and any(p.role == "owner" for p in people):
            raise HTTPException(400, "Es gibt schon einen Besitzer.")
        check_name(body.name)
        try:
            return _person(store.add_person(body.name, body.role))
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @router.patch("/people/{person_id}")
    def update_person(person_id: int, body: PersonPatch) -> PersonOut:
        require_person(person_id)
        if body.name is not None:
            check_name(body.name, person_id)
        store.update_person(person_id, name=body.name, voice_enabled=body.voice_enabled)
        return _person(require_person(person_id))

    @router.delete("/people/{person_id}", status_code=204)
    def remove_person(person_id: int) -> None:
        if require_person(person_id).role == "owner":
            raise HTTPException(400, "Der Besitzer kann nicht entfernt werden.")
        store.remove_person(person_id)

    @router.delete("/people/{person_id}/voice", status_code=204)
    def reset_voice(person_id: int) -> None:
        require_person(person_id)
        store.reset_voice(person_id)

    @router.get("/voice-claims")
    def voice_claims() -> list[VoiceClaimOut]:
        return [_claim(claim) for claim in store.voice_claims()]

    @router.post("/voice-claims/{claim_id}/confirm", status_code=204)
    def confirm_claim(claim_id: int, body: ConfirmClaim) -> None:
        person = require_person(body.person_id)
        if not person.voice_enabled:
            raise HTTPException(400, "Stimmerkennung ist für diese Person ausgeschaltet.")
        taken = store.take_voice_claim(claim_id)
        if taken is None:
            raise HTTPException(404, "Diese Anfrage gibt es nicht mehr.")
        current = store.voiceprints().get(person.id)
        vector, samples = merged(current[0] if current else None, current[1] if current else 0, taken[1])
        store.save_voiceprint(person.id, vector, samples)

    @router.delete("/voice-claims/{claim_id}", status_code=204)
    def reject_claim(claim_id: int) -> None:
        if store.take_voice_claim(claim_id) is None:
            raise HTTPException(404, "Diese Anfrage gibt es nicht mehr.")

    @router.get("/memories")
    def memories() -> list[MemoryOut]:
        return [_memory(memory) for memory in store.all_memories()]

    @router.post("/memories", status_code=201)
    def add_memory(body: MemoryIn) -> MemoryOut:
        if body.person_id is not None:
            require_person(body.person_id)
        return _memory(store.add_memory(body.person_id, "fact", body.text, source="control centre"))

    @router.patch("/memories/{memory_id}", status_code=204)
    def update_memory(memory_id: int, body: MemoryPatch) -> None:
        store.update_memory(memory_id, body.text)

    @router.delete("/memories/{memory_id}", status_code=204)
    def delete_memory(memory_id: int) -> None:
        if not store.delete_memory(memory_id):
            raise HTTPException(404, "Diesen Eintrag gibt es nicht mehr.")

    @router.get("/reminders")
    def reminders() -> list[ReminderOut]:
        return [_reminder(reminder) for reminder in store.reminders()]

    @router.delete("/reminders/{reminder_id}", status_code=204)
    def cancel_reminder(reminder_id: int) -> None:
        if not store.cancel_reminder(reminder_id):
            raise HTTPException(404, "Diese Erinnerung ist nicht mehr offen.")

    @router.get("/devices")
    def devices() -> list[DeviceOut]:
        return [_device(device) for device in store.devices()]

    @router.post("/devices/pair")
    def pair_device(body: PairDevice) -> DeviceOut:
        from pebbo.devices.gateway import pair

        device = pair(store, body.code)
        if device is None:
            raise HTTPException(404, "Kein Gerät zeigt diesen Code. Prüfe ihn oder starte das Gerät neu.")
        return _device(device)

    @router.patch("/devices/{device_id}")
    def rename_device(device_id: int, body: DevicePatch) -> DeviceOut:
        if store.device_by_id(device_id) is None:
            raise HTTPException(404, "Dieses Gerät gibt es nicht.")
        store.rename_device(device_id, body.name)
        device = store.device_by_id(device_id)
        if device is None:
            raise HTTPException(404, "Dieses Gerät gibt es nicht.")
        return _device(device)

    @router.delete("/devices/{device_id}", status_code=204)
    async def remove_device(device_id: int) -> None:
        from pebbo.devices.gateway import disconnect

        if not store.remove_device(device_id):
            raise HTTPException(404, "Dieses Gerät gibt es nicht.")
        await disconnect(device_id)

    return router
