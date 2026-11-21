"""Tools from MCP servers, tested against a fake Home Assistant MCP server on 127.0.0.1."""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
import uvicorn
from fastapi.testclient import TestClient
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent
from starlette.types import ASGIApp, Receive, Scope, Send

from pebbo import netguard
from pebbo.app import create_app
from pebbo.store import McpServer, Store
from pebbo.tools.mcp import (
    DONE,
    FAILED,
    LIVE_MAX_CHARS,
    NOT_LOCAL,
    TOKEN_REFUSED,
    UNREACHABLE,
    McpTools,
    check_address,
    live_summary,
    spoken_result,
    tool_name,
)
from pebbo.tools.registry import GUEST_UNKNOWN, OWNER_ONLY, ToolContext, ToolRegistry
from pebbo.voice.assistant import NO_DEVICES_RULE, context_message
from pebbo.voice.session import ConversationState

TOKEN = "synthetic-test-token"  # noqa: S105 (a fake token for the fake server)

LIVE = (
    "Live Context: An overview of the areas and the devices in this smart home:\n"
    "- names: Stehlampe\n"
    "  domain: light\n"
    "  state: 'on'\n"
    "  areas: Wohnzimmer\n"
    "  attributes:\n"
    "    brightness: '180'\n"
    "- names: Küche Lautsprecher\n"
    "  domain: media_player\n"
    "  state: playing\n"
    "  areas: Küche\n"
    "  attributes:\n"
    "    media_title: Testlied\n"
)


def fake_home_assistant() -> MCPServer:
    """Tools shaped like the ones Home Assistant's MCP server offers, on synthetic devices."""
    server = MCPServer("Fake Home Assistant")
    calls: list[tuple[str, dict[str, Any]]] = []

    @server.tool(name="HassTurnOn", description="Turns on/opens/presses a device or entity.")
    def turn_on(name: str, area: str = "") -> str:
        calls.append(("HassTurnOn", {"name": name, "area": area}))
        response = {
            "speech": {},
            "response_type": "action_done",
            "data": {"targets": [], "success": [{"name": name, "type": "entity"}], "failed": []},
        }
        return json.dumps(response)

    @server.tool(name="HassMediaPause", description="Pauses a media player.")
    def pause(name: str) -> str:
        return json.dumps(
            {"speech": {"plain": {"speech": "Musik pausiert."}}, "response_type": "action_done"}
        )

    @server.tool(name="Greeting", description="Says hello.")
    def greeting() -> str:
        return "Hallo aus dem Test."

    @server.tool(name="Broken", description="Always fails.")
    def broken() -> str:
        raise RuntimeError("synthetic failure")

    @server.tool(name="GetLiveContext", description="Current state of all devices.")
    def live() -> str:
        return json.dumps({"success": True, "result": LIVE})

    @server.tool(name="assist__GetDateTime", description="Current date and time.")
    def date_time() -> str:
        return json.dumps({"success": True, "result": {"date": "2026-01-01"}})

    server.calls = calls  # type: ignore[attr-defined]
    return server


class RequireToken:
    """Refuses requests without the fake token, as Home Assistant does."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            if headers.get(b"authorization") != f"Bearer {TOKEN}".encode():
                await send({"type": "http.response.start", "status": 401, "headers": []})
                await send({"type": "http.response.body", "body": b""})
                return
        await self._app(scope, receive, send)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture(scope="module")
def server_url() -> Iterator[str]:
    port = free_port()
    mcp_server = fake_home_assistant()
    app = RequireToken(mcp_server.streamable_http_app(stateless_http=True, json_response=True))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(5)


@pytest.fixture
def store() -> Store:
    return Store(":memory:")


def context(store: Store, role: str | None) -> ToolContext:
    person = None
    if role is not None:
        person = store.add_person(f"Person {len(store.people())}", role)  # type: ignore[arg-type]
    return ToolContext(store, person, ConversationState(store, recognizer=None))


def test_tools_are_listed_with_prefixes_and_permissions(store: Store, server_url: str) -> None:
    registry = ToolRegistry()
    integrations = McpTools(store, registry)
    server = store.add_mcp_server("Home Assistant", server_url, TOKEN)

    status = asyncio.run(integrations.refresh_server(server.id))

    assert status.state == "connected", status.message
    assert sorted(status.tools) == [
        "home_assistant_Broken",
        "home_assistant_Greeting",
        "home_assistant_HassMediaPause",
        "home_assistant_HassTurnOn",
    ]
    assert status.live_context
    tool = registry.get("home_assistant_HassTurnOn")
    assert tool is not None
    assert tool.source == "mcp:Home Assistant" and tool.permission == "household"
    assert tool.description.startswith("Home Assistant: Turns on")
    assert tool.parameters["type"] == "object" and "name" in tool.parameters["properties"]
    # The live context is put into Pebbo's context instead of being an action.
    assert registry.get("home_assistant_GetLiveContext") is None
    assert registry.get("home_assistant_assist__GetDateTime") is None


def test_calls_speak_short_german_results(store: Store, server_url: str) -> None:
    registry = ToolRegistry()
    integrations = McpTools(store, registry)
    server = store.add_mcp_server("Home Assistant", server_url, TOKEN)
    asyncio.run(integrations.refresh_server(server.id))
    member = context(store, "owner")

    async def call(tool: str, **arguments: Any) -> tuple[str, bool]:
        result = await registry.call(f"home_assistant_{tool}", arguments, member)
        return result.say, result.ok

    assert asyncio.run(call("HassTurnOn", name="Stehlampe")) == (DONE, True)
    assert asyncio.run(call("HassMediaPause", name="Küche")) == ("Musik pausiert.", True)
    assert asyncio.run(call("Greeting")) == ("Hallo aus dem Test.", True)
    assert asyncio.run(call("Broken")) == (FAILED, False)


def test_guests_and_non_owners_are_refused_by_the_registry(store: Store, server_url: str) -> None:
    registry = ToolRegistry()
    integrations = McpTools(store, registry)
    household = store.add_mcp_server("Home Assistant", server_url, TOKEN)
    private = store.add_mcp_server("Garage", server_url, TOKEN, "owner")
    asyncio.run(integrations.refresh_server(household.id))
    asyncio.run(integrations.refresh_server(private.id))

    guest = context(store, None)
    result = asyncio.run(registry.call("home_assistant_HassTurnOn", {"name": "Stehlampe"}, guest))
    assert result.say == GUEST_UNKNOWN and result.outcome == "denied"
    child = context(store, "child")
    assert asyncio.run(registry.call("garage_Greeting", {}, child)).say == OWNER_ONLY
    assert asyncio.run(registry.call("home_assistant_Greeting", {}, child)).ok
    # Device states of an owner-only server reach only the owner.
    assert len(asyncio.run(registry.context(child))) == 1
    assert len(asyncio.run(registry.context(context(store, "owner")))) == 2
    # Guests never get the device states, even from a server everyone may use.
    store.update_mcp_server(household.id, permission="everyone")
    asyncio.run(integrations.refresh_server(household.id))
    assert asyncio.run(registry.context(guest)) == []


def test_device_states_go_into_the_context_of_household_members(store: Store, server_url: str) -> None:
    registry = ToolRegistry()
    integrations = McpTools(store, registry)
    server = store.add_mcp_server("Home Assistant", server_url, TOKEN)
    asyncio.run(integrations.refresh_server(server.id))
    member = context(store, "adult")

    texts = asyncio.run(registry.context(member))

    assert len(texts) == 1
    # Grouped by room, so the action agent passes the room as the area and the bare device name.
    assert "- Bereich Wohnzimmer:\n  - Stehlampe: an" in texts[0]
    assert "- Bereich Küche:\n  - Küche Lautsprecher: spielt, media_title Testlied" in texts[0]
    state = ConversationState(store, recognizer=None)
    state.person = member.person
    assert "  - Stehlampe: an" in context_message(state, extra=texts)
    # Pebbo says honestly that it cannot switch devices only when no integration lists any.
    assert NO_DEVICES_RULE not in context_message(state, extra=texts)
    assert NO_DEVICES_RULE in context_message(state)
    state.person = None
    assert "Stehlampe" not in context_message(state, extra=texts)


def test_a_dead_or_refusing_server_never_raises(store: Store, server_url: str) -> None:
    registry = ToolRegistry()
    integrations = McpTools(store, registry)
    dead = store.add_mcp_server("Tot", f"http://127.0.0.1:{free_port()}/mcp", "")
    wrong = store.add_mcp_server("Falsch", server_url, "wrong-token")

    assert asyncio.run(integrations.refresh_server(dead.id)).message == UNREACHABLE
    assert asyncio.run(integrations.refresh_server(wrong.id)).message == TOKEN_REFUSED
    assert registry.tools() == []
    asyncio.run(integrations.refresh())

    # A server that goes away after listing answers with a short sentence.
    good = store.add_mcp_server("Home Assistant", server_url, TOKEN)
    asyncio.run(integrations.refresh_server(good.id))
    store.update_mcp_server(good.id, url=f"http://127.0.0.1:{free_port()}/mcp")
    result = asyncio.run(registry.call("home_assistant_Greeting", {}, context(store, "owner")))
    assert (result.say, result.ok) == (FAILED, False)


@asynccontextmanager
async def no_network(server: McpServer) -> AsyncIterator[Any]:
    """Checks the address like a real session, then fails without opening any connection.

    The guards do not see asyncio connections on Windows, so tests with public addresses must
    never reach a real session.
    """
    await check_address(server)
    raise ConnectionRefusedError("No network in tests.")
    yield  # pragma: no cover


def test_public_addresses_need_the_owners_permission(store: Store) -> None:
    registry = ToolRegistry()
    integrations = McpTools(store, registry, session=no_network)
    server = store.add_mcp_server("Cloud", "https://8.8.8.8/api/mcp", TOKEN)

    status = asyncio.run(integrations.refresh_server(server.id))
    assert status.state == "error" and status.message == NOT_LOCAL
    assert integrations.public_hosts() == set()

    store.update_mcp_server(server.id, allow_public=True)
    try:
        status = asyncio.run(integrations.refresh_server(server.id))
        assert status.state == "error" and status.message == UNREACHABLE
        assert integrations.public_hosts() == {"8.8.8.8"}
        assert netguard._host_allowed("8.8.8.8")
        store.update_mcp_server(server.id, enabled=False)
        assert asyncio.run(integrations.refresh_server(server.id)).state == "disabled"
        assert integrations.public_hosts() == set()
        assert not netguard._host_allowed("8.8.8.8")
    finally:
        netguard.revoke(["8.8.8.8"])


def test_disabling_and_removing_a_server_removes_its_tools(store: Store, server_url: str) -> None:
    registry = ToolRegistry()
    integrations = McpTools(store, registry)
    server = store.add_mcp_server("Home Assistant", server_url, TOKEN)
    asyncio.run(integrations.refresh_server(server.id))
    assert registry.tools()

    store.update_mcp_server(server.id, enabled=False)
    assert asyncio.run(integrations.refresh_server(server.id)).state == "disabled"
    assert registry.tools() == []
    store.update_mcp_server(server.id, enabled=True)
    asyncio.run(integrations.refresh_server(server.id))
    store.remove_mcp_server(server.id)
    integrations.forget(server.id)
    assert registry.tools() == []


def test_control_api_never_returns_the_token(store: Store, server_url: str) -> None:
    client = TestClient(create_app(store=store))

    created = client.post(
        "/api/control/integrations",
        json={"name": "Home Assistant", "url": server_url, "token": TOKEN},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["has_token"] and body["permission"] == "household" and body["enabled"]
    assert body["status"]["state"] == "connected"
    assert "home_assistant_HassTurnOn" in body["status"]["tools"]
    assert (
        client.post(
            "/api/control/integrations", json={"name": "home assistant", "url": server_url}
        ).status_code
        == 400
    )
    assert client.post("/api/control/integrations", json={"name": "X", "url": "ftp://x"}).status_code == 422

    server_id = body["id"]
    patched = client.patch(f"/api/control/integrations/{server_id}", json={"permission": "owner"})
    assert patched.json()["permission"] == "owner" and patched.json()["has_token"]
    listed = client.get("/api/control/integrations")
    assert TOKEN not in listed.text and TOKEN not in created.text and TOKEN not in patched.text
    assert client.post(f"/api/control/integrations/{server_id}/refresh").json()["status"]["state"] == (
        "connected"
    )
    cleared = client.patch(f"/api/control/integrations/{server_id}", json={"token": ""}).json()
    assert not cleared["has_token"] and cleared["status"]["message"] == TOKEN_REFUSED
    assert client.delete(f"/api/control/integrations/{server_id}").status_code == 204
    assert client.get("/api/control/integrations").json() == []
    assert client.delete(f"/api/control/integrations/{server_id}").status_code == 404


def test_tool_names_are_valid_and_unique_per_server() -> None:
    assert tool_name("Home Assistant", "HassTurnOn") == "home_assistant_HassTurnOn"
    assert tool_name("Küche & Bad", "Turn on.") == "kueche_bad_Turn_on_"
    assert len(tool_name("x" * 50, "y" * 50)) <= 64


def test_results_without_text_or_with_long_text() -> None:
    long_text = CallToolResult(content=[TextContent(type="text", text="Wort " * 100)])
    query = CallToolResult(content=[TextContent(type="text", text='{"response_type": "query_answer"}')])
    failed = CallToolResult(content=[TextContent(type="text", text='{"response_type": "error"}')])
    assert spoken_result(long_text).say == DONE
    assert spoken_result(query).say == "" and spoken_result(query).ok
    assert spoken_result(failed).say == FAILED
    assert spoken_result(CallToolResult(content=[], is_error=True)).say == FAILED


def test_live_summary_is_capped() -> None:
    many = "Live Context:\n" + "".join(f"- names: Lampe {i}\n  state: 'off'\n" for i in range(200))
    summary = live_summary("Home Assistant", many)
    assert len(summary) <= LIVE_MAX_CHARS
    assert summary.endswith("- …") and "- Lampe 0: aus" in summary


def test_live_summary_groups_devices_by_room() -> None:
    raw = (
        "Live Context:\n- names: Flurlicht\n  state: 'on'\n"
        "- names: Deckenlicht\n  state: 'off'\n  areas: Wohnzimmer\n"
        "- names: Herd\n  state: 'off'\n  areas: Küche\n"
        "- names: Stehlampe\n  state: 'on'\n  areas: Wohnzimmer\n"
    )
    assert live_summary("HA", raw).splitlines()[1:] == [
        "- Flurlicht: an",
        "- Bereich Wohnzimmer:",
        "  - Deckenlicht: aus",
        "  - Stehlampe: an",
        "- Bereich Küche:",
        "  - Herd: aus",
    ]
