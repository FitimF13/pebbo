"""Control centre API for integrations: MCP servers such as Home Assistant.

Served under ``/api/control/integrations`` and, like the rest of the control centre, only
on this computer (see ``pebbo.access``). The access token is write-only: the API accepts
it but never returns it, only whether one is stored.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from pebbo.store import IntegrationPermission, McpServer, Store
from pebbo.tools.mcp import McpTools, ServerStatus, public_host, slug

_URL = r"^https?://\S+$"


class IntegrationStatusOut(BaseModel):
    state: str
    message: str
    tools: list[str]
    live_context: bool
    checked_at: float | None


class IntegrationOut(BaseModel):
    id: int
    name: str
    url: str
    permission: IntegrationPermission
    enabled: bool
    allow_public: bool
    has_token: bool
    # The public host the network guard lets through for this server, if the owner allowed one.
    public_host: str | None
    status: IntegrationStatusOut


class IntegrationIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    url: str = Field(min_length=8, max_length=300, pattern=_URL)
    token: str = Field(default="", max_length=2000)
    permission: IntegrationPermission = "household"
    enabled: bool = True
    allow_public: bool = False


class IntegrationPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    url: str | None = Field(default=None, min_length=8, max_length=300, pattern=_URL)
    # None keeps the stored token, an empty string removes it.
    token: str | None = Field(default=None, max_length=2000)
    permission: IntegrationPermission | None = None
    enabled: bool | None = None
    allow_public: bool | None = None


def _status(status: ServerStatus) -> IntegrationStatusOut:
    return IntegrationStatusOut(
        state=status.state,
        message=status.message,
        tools=status.tools,
        live_context=status.live_context,
        checked_at=status.checked_at,
    )


def integrations_router(store: Store, integrations: McpTools) -> APIRouter:
    router = APIRouter(prefix="/api/control/integrations")

    def out(server: McpServer) -> IntegrationOut:
        return IntegrationOut(
            id=server.id,
            name=server.name,
            url=server.url,
            permission=server.permission,
            enabled=server.enabled,
            allow_public=server.allow_public,
            has_token=bool(server.token),
            public_host=public_host(server),
            status=_status(integrations.status(server.id)),
        )

    def require(server_id: int) -> McpServer:
        server = store.mcp_server(server_id)
        if server is None:
            raise HTTPException(404, "Diese Integration gibt es nicht.")
        return server

    def check_name(name: str, server_id: int | None = None) -> None:
        taken = any(slug(other.name) == slug(name) and other.id != server_id for other in store.mcp_servers())
        if taken:
            raise HTTPException(400, "Eine Integration mit diesem Namen gibt es schon.")

    @router.get("")
    def list_integrations() -> list[IntegrationOut]:
        return [out(server) for server in store.mcp_servers()]

    @router.post("", status_code=201)
    async def add_integration(body: IntegrationIn) -> IntegrationOut:
        check_name(body.name)
        try:
            server = store.add_mcp_server(
                body.name,
                body.url,
                body.token.strip(),
                body.permission,
                enabled=body.enabled,
                allow_public=body.allow_public,
            )
        except sqlite3.IntegrityError as error:
            raise HTTPException(400, "Eine Integration mit diesem Namen gibt es schon.") from error
        await integrations.refresh_server(server.id)
        return out(require(server.id))

    @router.patch("/{server_id}")
    async def update_integration(server_id: int, body: IntegrationPatch) -> IntegrationOut:
        require(server_id)
        if body.name is not None:
            check_name(body.name, server_id)
        try:
            store.update_mcp_server(
                server_id,
                name=body.name,
                url=body.url,
                token=body.token.strip() if body.token is not None else None,
                permission=body.permission,
                enabled=body.enabled,
                allow_public=body.allow_public,
            )
        except sqlite3.IntegrityError as error:
            raise HTTPException(400, "Eine Integration mit diesem Namen gibt es schon.") from error
        await integrations.refresh_server(server_id)
        return out(require(server_id))

    @router.post("/{server_id}/refresh")
    async def refresh_integration(server_id: int) -> IntegrationOut:
        require(server_id)
        await integrations.refresh_server(server_id)
        return out(require(server_id))

    @router.delete("/{server_id}", status_code=204)
    def remove_integration(server_id: int) -> None:
        if not store.remove_mcp_server(server_id):
            raise HTTPException(404, "Diese Integration gibt es nicht.")
        integrations.forget(server_id)

    return router
