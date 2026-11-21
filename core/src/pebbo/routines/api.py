"""Control centre API for routines: list, pause and resume, approve, test, delete, run log.

Like the rest of the control centre it answers only on this computer (see ``pebbo.access``)
and acts for the owner, so approving a routine here is the owner's approval.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from pebbo.routines.engine import RoutineScheduler
from pebbo.routines.storage import Routine, RoutineRun
from pebbo.routines.tools import dry_run, routine_text
from pebbo.store import Store


class RoutineOut(BaseModel):
    id: int
    person_id: int
    name: str
    text: str
    description: str
    status: Literal["draft", "active", "paused"]
    waiting_for_owner: bool
    needs_owner: bool
    trigger: dict[str, Any]
    conditions: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    report: bool
    cooldown_minutes: int
    daily_limit: int
    created_at: float
    last_run_at: float | None


class RoutineRunOut(BaseModel):
    id: int
    routine_id: int
    started_at: float
    trigger: str
    conditions: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    result: str
    dry_run: bool


class RoutineStatusIn(BaseModel):
    status: Literal["active", "paused"]


class RoutineTestOut(BaseModel):
    say: str
    run: RoutineRunOut


def _run(run: RoutineRun) -> RoutineRunOut:
    return RoutineRunOut(
        id=run.id,
        routine_id=run.routine_id,
        started_at=run.started_at,
        trigger=run.trigger,
        conditions=run.conditions,
        actions=run.actions,
        result=run.result,
        dry_run=run.dry_run,
    )


def routines_router(store: Store, scheduler: RoutineScheduler) -> APIRouter:
    router = APIRouter(prefix="/api/control")
    book = scheduler.book

    def out(routine: Routine) -> RoutineOut:
        # Described for the person who taught it, as they would hear it.
        description = routine_text(routine, store, store.person(routine.person_id))
        return RoutineOut(
            id=routine.id,
            person_id=routine.person_id,
            name=routine.name,
            text=routine.text,
            description=description,
            status=routine.status,
            waiting_for_owner=routine.waiting_for_owner,
            needs_owner=routine.needs_owner,
            trigger=routine.trigger,
            conditions=routine.conditions,
            actions=routine.actions,
            report=routine.report,
            cooldown_minutes=routine.cooldown_minutes,
            daily_limit=routine.daily_limit,
            created_at=routine.created_at,
            last_run_at=routine.last_run_at,
        )

    def require(routine_id: int) -> Routine:
        routine = book.routine(routine_id)
        if routine is None:
            raise HTTPException(404, "Diese Routine gibt es nicht mehr.")
        return routine

    @router.get("/routines")
    def routines() -> list[RoutineOut]:
        return [out(routine) for routine in book.routines()]

    @router.post("/routines/{routine_id}/status")
    def set_status(routine_id: int, body: RoutineStatusIn) -> RoutineOut:
        routine = require(routine_id)
        if body.status == "active":
            if routine.status == "draft" and not routine.waiting_for_owner:
                raise HTTPException(400, "Diese Routine hat die Person noch nicht bestätigt.")
            owner = next((p for p in store.people() if p.role == "owner"), None)
            book.activate(routine_id, approved_by=owner.id if routine.needs_owner and owner else None)
        else:
            if routine.status == "draft":
                raise HTTPException(400, "Ein Entwurf kann nicht pausiert werden.")
            book.set_status(routine_id, "paused")
        return out(require(routine_id))

    @router.delete("/routines/{routine_id}", status_code=204)
    def delete(routine_id: int) -> None:
        if not book.delete(routine_id):
            raise HTTPException(404, "Diese Routine gibt es nicht mehr.")

    @router.post("/routines/{routine_id}/test")
    async def test(routine_id: int) -> RoutineTestOut:
        routine = require(routine_id)
        say = await dry_run(scheduler.engine, routine)
        return RoutineTestOut(say=say, run=_run(book.runs(routine_id, limit=1)[0]))

    @router.get("/routine-runs")
    def runs(routine_id: int | None = None, limit: int = 50) -> list[RoutineRunOut]:
        return [_run(run) for run in book.runs(routine_id, limit=max(1, min(limit, 200)))]

    return router
