"""Control centre API for compute devices: where Pebbo's language model runs."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from pebbo.models_router import ComputeDevice, ModelRouter


class DeviceIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    base_url: str = Field(min_length=8, max_length=200)
    model: str = Field(min_length=1, max_length=80)


class Move(BaseModel):
    position: int


def compute_router(router: ModelRouter) -> APIRouter:
    api = APIRouter(prefix="/api/control/compute")

    def out(device: ComputeDevice) -> dict[str, Any]:
        return {
            "id": device.id,
            "name": device.name,
            "base_url": device.base_url,
            "model": device.model,
            "position": device.position,
            "reachable": router.reachable(device),
            "active": router.current().id == device.id,
            "removable": device.id != 0,
        }

    @api.get("")
    def devices() -> list[dict[str, Any]]:
        return [out(device) for device in router.devices()]

    @api.post("", status_code=201)
    async def add(body: DeviceIn) -> dict[str, Any]:
        try:
            device = router.add(body.name, body.base_url, body.model)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        await asyncio.to_thread(router.refresh)
        return out(device)

    @api.post("/check")
    async def check() -> list[dict[str, Any]]:
        await asyncio.to_thread(router.refresh)
        return [out(device) for device in router.devices()]

    @api.patch("/{device_id}", status_code=204)
    def move(device_id: int, body: Move) -> None:
        router.move(device_id, body.position)

    @api.delete("/{device_id}", status_code=204)
    def remove(device_id: int) -> None:
        if device_id == 0 or not router.remove(device_id):
            raise HTTPException(404, "Diesen Rechner gibt es nicht oder er lässt sich nicht entfernen.")

    return api
