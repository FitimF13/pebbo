"""HTTP endpoints for two Pebbos: what other instances may call, and the owner's control."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from pebbo.instances.peers import Handoff, Peer, PeerError, Peers
from pebbo.tools.registry import Tool, ToolContext, ToolRegistry, ToolResult, speaker, text_argument


class PairRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)
    name: str = Field(min_length=1, max_length=40)
    address: str = Field(min_length=8, max_length=200)
    token: str = Field(min_length=20, max_length=200)


class HandoffIn(BaseModel):
    person: str = Field(max_length=60)
    content: str = Field(min_length=1, max_length=2000)


class ConnectRequest(BaseModel):
    address: str = Field(min_length=8, max_length=200, pattern=r"^https?://")
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class Decision(BaseModel):
    approve: bool


def _peer(peer: Peer) -> dict[str, Any]:
    return {"id": peer.id, "name": peer.name, "address": peer.address, "created_at": peer.created_at}


def _handoff(handoff: Handoff) -> dict[str, Any]:
    return {
        "id": handoff.id,
        "peer": handoff.peer_name,
        "direction": handoff.direction,
        "person": handoff.person_name,
        "content": handoff.content,
        "status": handoff.status,
        "created_at": handoff.created_at,
        "decided_at": handoff.decided_at,
    }


def peer_router(peers: Peers) -> APIRouter:
    """What another paired instance may call. It can only deliver handoffs, never read."""
    router = APIRouter(prefix="/api/peer")

    @router.post("/pair")
    def pair(body: PairRequest) -> dict[str, str]:
        try:
            token = peers.accept(body.code, body.name, body.address, body.token)
        except PeerError as error:
            raise HTTPException(403, str(error)) from error
        return {"token": token, "name": peers.name}

    @router.post("/handoff")
    def handoff(body: HandoffIn, authorization: str = Header(default="")) -> dict[str, Any]:
        token = authorization.split(" ", 1)[1] if authorization.lower().startswith("bearer ") else ""
        peer = peers.peer_by_token(token)
        if peer is None:
            raise HTTPException(401, "Unbekannte Instanz.")
        return _handoff(peers.receive(peer, body.person, body.content))

    return router


def instance_control_router(peers: Peers) -> APIRouter:
    """The owner's side in the control centre (local only, like the rest of it)."""
    router = APIRouter(prefix="/api/control/instances")

    @router.get("")
    def overview() -> dict[str, Any]:
        return {
            "name": peers.name,
            "address": peers.own_address,
            "peers": [_peer(p) for p in peers.peers()],
            "handoffs": [_handoff(h) for h in peers.handoffs()],
        }

    @router.post("/invite")
    def invite() -> dict[str, str]:
        return {"code": peers.invite()}

    @router.post("/connect")
    def connect(body: ConnectRequest) -> dict[str, Any]:
        try:
            return _peer(peers.connect(body.address, body.code))
        except PeerError as error:
            raise HTTPException(400, str(error)) from error

    @router.delete("/{peer_id}", status_code=204)
    def remove(peer_id: int) -> None:
        if not peers.remove(peer_id):
            raise HTTPException(404, "Diese Instanz ist nicht verbunden.")

    @router.post("/handoffs/{handoff_id}")
    def decide(handoff_id: int, body: Decision) -> dict[str, Any]:
        try:
            return _handoff(peers.decide(handoff_id, body.approve))
        except PeerError as error:
            raise HTTPException(400, str(error)) from error

    return router


def register_handoff_tool(registry: ToolRegistry, peers: Peers) -> None:
    """Let Pebbo prepare an end-of-day handoff to the other instance, for the owner to approve."""

    async def prepare_handoff(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        person = speaker(context)
        content = text_argument(arguments, "content")
        if not content:
            return ToolResult(ok=False, outcome="empty")
        try:
            handoff = peers.prepare(person.name, content, text_argument(arguments, "to"))
        except PeerError as error:
            return ToolResult(str(error), ok=False, outcome="no-peer")
        return ToolResult(
            f"Die Übergabe an {handoff.peer_name} ist vorbereitet. "
            "Gib sie im Kontrollzentrum frei, dann schicke ich sie.",
            outcome="prepared",
        )

    registry.register(
        Tool(
            name="prepare_handoff",
            description=(
                "Bereitet eine Übergabe an die andere Pebbo-Instanz vor (zum Beispiel Büro an Zuhause am "
                "Feierabend): offene Aufgaben, Nachfassen, Erinnerungen für später. Nur wenn die Person das "
                "möchte. Gesendet wird erst nach der Freigabe im Kontrollzentrum."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Was übergeben werden soll, kurz und klar"},
                    "to": {"type": "string", "description": "Name der anderen Instanz, sonst leer"},
                },
                "required": ["content"],
            },
            run=prepare_handoff,
        )
    )
