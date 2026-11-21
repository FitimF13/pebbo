"""Tools from MCP servers, for example Home Assistant and, through it, Music Assistant.

The owner adds MCP servers in the control centre (name, URL, access token, permission).
Pebbo connects to each enabled server over Streamable HTTP, lists its tools and registers
every one in the :class:`~pebbo.tools.registry.ToolRegistry` under the source
``mcp:<server name>``, with the server's name as a prefix so tool names stay unique. The
action agent then picks them by their descriptions like Pebbo's own tools, and the registry
checks the server's permission before a tool runs. No command words are involved.

Rules:

- A server must be on the home network (a private or loopback address) unless the owner
  explicitly allowed a public host for it. Only then is the host added to the runtime network
  guard (``pebbo.netguard``), and removed again when it is no longer needed.
- A server that is down or misbehaves never breaks the conversation: listing and calling
  report a status or a short German sentence instead of raising.
- Tokens and tool arguments are never logged at ``INFO``.

Pebbo opens a fresh MCP session for each call. On the home network this costs a few
milliseconds and avoids stale sessions after the server restarts.
"""

from __future__ import annotations

import asyncio
import json
import re
import socket
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx2
from loguru import logger
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, Implementation, TextContent
from mcp.types import Tool as McpTool

from pebbo import __version__, netguard
from pebbo.store import McpServer, Store
from pebbo.tools.registry import ContextSource, Tool, ToolContext, ToolRegistry, ToolResult

DONE = "Erledigt."
FAILED = "Das hat nicht geklappt."
NOT_LOCAL = (
    "Diese Adresse liegt nicht im Heimnetz. Erlaube die öffentliche Adresse ausdrücklich, "
    "wenn du ihr vertraust."
)
BAD_URL = "Die Adresse muss mit http:// oder https:// beginnen."
NOT_FOUND = "Diese Adresse finde ich nicht."
UNREACHABLE = "Nicht erreichbar. Läuft der Server und stimmt die Adresse?"
TOKEN_REFUSED = "Der Server hat den Zugangstoken abgelehnt."  # noqa: S105 (a message)
DISABLED = "Ausgeschaltet."

# Seconds to connect and list a server's tools.
LIST_TIMEOUT = 8.0
# Seconds a single tool call may take. Pebbo's answer waits for it, so keep it short.
CALL_TIMEOUT = 6.0
# A text result up to this length is spoken as it is, for example Home Assistant's "speech".
SHORT_TEXT = 160
# Tool descriptions are cut to this length, so many tools fit into the action agent's context.
MAX_DESCRIPTION = 400

# Home Assistant's tool with the state of all exposed devices. Pebbo puts a summary of it into
# its context instead of offering it as an action, because the answer is already being written
# while the action agent decides.
LIVE_CONTEXT_TOOL = "getlivecontext"
# Tools Pebbo does not offer because it covers them itself.
SKIPPED_TOOLS = frozenset({"getdatetime"})
# The device summary is refreshed at most this often and cut to this many characters.
LIVE_SECONDS = 30.0
LIVE_MAX_CHARS = 1200
# How long an answer waits for a stale device summary before it goes on without the new one.
LIVE_WAIT_SECONDS = 1.0

State = Literal["connected", "error", "disabled"]


class HostNotAllowed(Exception):
    """The server's address is not allowed. The message is German and meant for the owner."""


class TokenRefused(Exception):
    """The server answered 401 or 403."""


@dataclass
class ServerStatus:
    """How the connection to a server went the last time Pebbo tried."""

    state: State
    message: str = ""
    tools: list[str] = field(default_factory=list)
    live_context: bool = False
    checked_at: float | None = None


@dataclass
class _Live:
    tool: str
    text: str = ""
    fetched_at: float = -LIVE_SECONDS
    task: asyncio.Task[None] | None = None


def slug(name: str) -> str:
    """A short ASCII prefix for tool names, for example ``home_assistant`` for "Home Assistant"."""
    text = name.lower()
    for umlaut, plain in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(umlaut, plain)
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text[:24].rstrip("_") or "mcp"


def tool_name(server_name: str, name: str) -> str:
    """The name the action agent sees, unique across servers and valid as a function name."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", f"{slug(server_name)}_{name}")[:64]


def source_of(server: McpServer) -> str:
    return f"mcp:{server.name}"


def parameters(schema: dict[str, Any] | None) -> dict[str, Any]:
    """The server's JSON schema as function parameters, always an object."""
    result = {key: value for key, value in (schema or {}).items() if key != "$schema"}
    result.setdefault("type", "object")
    result.setdefault("properties", {})
    return result


def _text(result: CallToolResult) -> str:
    return "\n".join(block.text for block in result.content if isinstance(block, TextContent)).strip()


def _payload(result: CallToolResult, text: str) -> Any:
    """The JSON in the text result, else the structured result, else ``None`` for plain text."""
    if text[:1] in "{[":
        try:
            return json.loads(text)
        except ValueError:
            return None
    if not text and isinstance(result.structured_content, dict):
        return result.structured_content
    return None


def _speech(payload: dict[str, Any]) -> str:
    """The "speech" of a Home Assistant intent response, if any."""
    speech = payload.get("speech")
    if isinstance(speech, dict):
        plain = speech.get("plain")
        if isinstance(plain, dict) and isinstance(plain.get("speech"), str):
            return str(plain["speech"]).strip()
    return ""


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= SHORT_TEXT else ""


def spoken_result(result: CallToolResult) -> ToolResult:
    """Turn a tool result into the short sentence Pebbo says after its answer."""
    text = _text(result)
    if result.is_error:
        return ToolResult(FAILED, ok=False, outcome="failed")
    payload = _payload(result, text)
    if isinstance(payload, dict):
        raw = payload.get("data")
        data: dict[str, Any] = raw if isinstance(raw, dict) else {}
        failed = payload.get("response_type") == "error" or payload.get("success") is False
        if failed or (data.get("failed") and not data.get("success")):
            return ToolResult(FAILED, ok=False, outcome="failed")
        speech = _short(_speech(payload))
        if speech:
            return ToolResult(speech, outcome="done")
        if payload.get("response_type") == "query_answer":
            # Pebbo answers questions about devices from its context, not with "Erledigt.".
            return ToolResult(outcome="answered")
        return ToolResult(DONE, outcome="done")
    if payload is None and _short(text):
        return ToolResult(_short(text), outcome="done")
    return ToolResult(DONE, outcome="done")


_STATES = {
    "on": "an",
    "off": "aus",
    "playing": "spielt",
    "paused": "pausiert",
    "idle": "bereit",
    "standby": "Standby",
    "open": "offen",
    "closed": "geschlossen",
    "opening": "öffnet",
    "closing": "schliesst",
    "locked": "abgeschlossen",
    "unlocked": "aufgeschlossen",
    "home": "zu Hause",
    "not_home": "weg",
    "unavailable": "nicht erreichbar",
    "unknown": "unbekannt",
}
_ATTRIBUTES = ("current_temperature", "temperature", "media_title", "media_artist", "volume_level")


def _value(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        text = text[1:-1]
    return text


def _devices(text: str) -> list[dict[str, str]]:
    """Parse the YAML list in Home Assistant's live context without a YAML library."""
    devices: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if line.startswith("- "):
            current = {}
            devices.append(current)
            stripped = line[2:].strip()
        elif current is None or not line.startswith(" "):
            continue
        key, separator, value = stripped.partition(":")
        if separator and value.strip():
            current[key.strip()] = _value(value)
    return [device for device in devices if device.get("names")]


def live_summary(server_name: str, raw: str) -> str:
    """A compact summary of a live context result for Pebbo's context, at most ``LIVE_MAX_CHARS``."""
    text = raw
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = None
    if isinstance(payload, dict) and isinstance(payload.get("result"), str):
        text = payload["result"]
    lines = []
    for device in _devices(text):
        state = device.get("state", "")
        state = _STATES.get(state, state)
        if unit := device.get("unit_of_measurement"):
            state = f"{state} {unit}"
        extras = [f"{key} {device[key]}" for key in _ATTRIBUTES if device.get(key)]
        where = f" ({device['areas']})" if device.get("areas") else ""
        line = f"- {device['names']}{where}: {state}"
        lines.append(f"{line}, {', '.join(extras)}" if extras else line)
    if not lines:
        lines = [line for line in (part.strip() for part in text.splitlines()) if line][1:]
    header = (
        f"Geräte im Haus gerade jetzt, laut {server_name}. Fragen nach Geräten beantwortest du nur damit:"
    )
    summary = header
    for line in lines:
        if len(summary) + len(line) + 1 > LIVE_MAX_CHARS - 4:
            return f"{summary}\n- …"
        summary = f"{summary}\n{line}"
    return summary if lines else ""


async def check_address(server: McpServer) -> None:
    """Refuse servers outside the home network unless the owner allowed a public host."""
    parts = urlsplit(server.url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise HostNotAllowed(BAD_URL)
    if server.allow_public:
        return
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, parts.hostname, port, type=socket.SOCK_STREAM)
    except OSError as error:
        raise HostNotAllowed(NOT_FOUND) from error
    if not infos or any(not netguard.is_local_address(str(info[4][0])) for info in infos):
        raise HostNotAllowed(NOT_LOCAL)


def public_host(server: McpServer) -> str | None:
    """The host the network guard lets through for this server, if the owner allowed it."""
    if not (server.enabled and server.allow_public):
        return None
    host = urlsplit(server.url).hostname
    return host.lower() if host else None


@asynccontextmanager
async def open_session(server: McpServer) -> AsyncIterator[Client]:
    """An MCP session with the server, after checking its address."""
    await check_address(server)
    headers = {"Authorization": f"Bearer {server.token}"} if server.token else {}
    refused: list[int] = []

    async def note_refusal(response: httpx2.Response) -> None:
        # The MCP client turns HTTP errors into a generic error, so remember a refused token here.
        if response.status_code in (401, 403):
            refused.append(response.status_code)

    # trust_env=False: no proxy from the environment ever sees the token.
    http = httpx2.AsyncClient(
        headers=headers,
        timeout=httpx2.Timeout(LIST_TIMEOUT, read=CALL_TIMEOUT),
        trust_env=False,
        event_hooks={"response": [note_refusal]},
    )
    try:
        async with (
            http,
            Client(
                streamable_http_client(server.url, http_client=http),
                mode="legacy",
                client_info=Implementation(name="pebbo", version=__version__),
                read_timeout_seconds=CALL_TIMEOUT,
                cache=None,
            ) as client,
        ):
            yield client
    except Exception as error:
        if refused:
            raise TokenRefused(refused[0]) from error
        raise


def _causes(error: BaseException) -> list[BaseException]:
    found: list[BaseException] = []
    todo = [error]
    while todo and len(found) < 50:
        current = todo.pop()
        found.append(current)
        if isinstance(current, BaseExceptionGroup):
            todo.extend(current.exceptions)
        todo.extend(cause for cause in (current.__cause__, current.__context__) if cause is not None)
    return found


def describe(error: BaseException) -> str:
    """A short German reason for the owner. Never contains the token."""
    for cause in _causes(error):
        if isinstance(cause, HostNotAllowed):
            return str(cause)
        if isinstance(cause, TokenRefused) or (
            isinstance(cause, httpx2.HTTPStatusError) and cause.response.status_code in (401, 403)
        ):
            return TOKEN_REFUSED
    return UNREACHABLE


class McpTools:
    """Keeps the tools of all configured MCP servers in the registry."""

    def __init__(
        self, store: Store, registry: ToolRegistry, session: Callable[[McpServer], Any] = open_session
    ) -> None:
        self._store = store
        self._registry = registry
        self._session = session
        self._status: dict[int, ServerStatus] = {}
        self._sources: dict[int, str] = {}
        self._live: dict[int, _Live] = {}
        self._public_hosts: set[str] = set()

    def status(self, server_id: int) -> ServerStatus:
        return self._status.get(server_id, ServerStatus("error", "Noch nicht verbunden."))

    async def refresh(self) -> None:
        """Reconnect to every configured server, for example at startup. Never raises."""
        known = {server.id for server in self._store.mcp_servers()}
        for server_id in set(self._sources) - known:
            self.forget(server_id)
        for server_id in sorted(known):
            await self.refresh_server(server_id)

    def forget(self, server_id: int) -> None:
        """Remove a server's tools, for example after the owner deleted it."""
        self._drop(server_id)
        self._status.pop(server_id, None)
        self._sync_public_hosts()

    async def refresh_server(self, server_id: int) -> ServerStatus:
        """List the server's tools again and register them. Never raises."""
        self._drop(server_id)
        self._sync_public_hosts()
        server = self._store.mcp_server(server_id)
        if server is None:
            self._status.pop(server_id, None)
            return ServerStatus("disabled", DISABLED)
        if not server.enabled:
            status = ServerStatus("disabled", DISABLED, checked_at=time.time())
            self._status[server_id] = status
            return status
        try:
            async with asyncio.timeout(LIST_TIMEOUT):
                tools = await self._list(server)
        except Exception as error:
            status = ServerStatus("error", describe(error), checked_at=time.time())
            logger.warning("MCP server {} is not available: {}", server.id, type(error).__name__)
            self._status[server_id] = status
            return status
        status = self._register(server, tools)
        logger.info("MCP server {} offers {} tools", server.id, len(status.tools))
        self._status[server_id] = status
        return status

    async def _list(self, server: McpServer) -> list[McpTool]:
        tools: list[McpTool] = []
        async with self._session(server) as client:
            cursor: str | None = None
            for _page in range(20):
                page = await client.list_tools(cursor=cursor)
                tools += page.tools
                cursor = page.next_cursor
                if not cursor:
                    break
        return tools

    def _register(self, server: McpServer, tools: list[McpTool]) -> ServerStatus:
        source = source_of(server)
        self._sources[server.id] = source
        names: list[str] = []
        live: str | None = None
        for tool in tools:
            # Home Assistant prefixes tools with their set, for example "homeassistant__GetLiveContext".
            key = tool.name.rsplit("__", 1)[-1].lower()
            if key == LIVE_CONTEXT_TOOL:
                live = tool.name
                continue
            if key in SKIPPED_TOOLS:
                continue
            name = tool_name(server.name, tool.name)
            description = " ".join((tool.description or tool.title or tool.name).split())[:MAX_DESCRIPTION]
            self._registry.register(
                Tool(
                    name=name,
                    description=f"{server.name}: {description}",
                    parameters=parameters(tool.input_schema),
                    run=self._runner(server.id, tool.name),
                    permission=server.permission,
                    source=source,
                )
            )
            names.append(name)
        if live is not None:
            self._live[server.id] = _Live(live)
            self._registry.add_context(
                ContextSource(source, self._context_runner(server.id), permission=server.permission)
            )
        return ServerStatus("connected", "", names, live is not None, time.time())

    def _drop(self, server_id: int) -> None:
        source = self._sources.pop(server_id, None)
        if source is not None:
            self._registry.unregister_source(source)
        self._live.pop(server_id, None)

    def _sync_public_hosts(self) -> None:
        """Let exactly the public hosts the owner allowed through the network guard."""
        wanted = {host for server in self._store.mcp_servers() if (host := public_host(server))}
        added, removed = wanted - self._public_hosts, self._public_hosts - wanted
        if added:
            netguard.allow(added)
            logger.info("Network guard allows the public integration hosts {}", sorted(added))
        if removed:
            netguard.revoke(removed)
        self._public_hosts = wanted

    def public_hosts(self) -> set[str]:
        return set(self._public_hosts)

    async def call(self, server_id: int, name: str, arguments: dict[str, Any]) -> CallToolResult:
        """Call a tool on a server. Raises if the server is gone or does not answer."""
        server = self._store.mcp_server(server_id)
        if server is None or not server.enabled:
            raise LookupError("The integration is no longer enabled.")
        async with asyncio.timeout(CALL_TIMEOUT), self._session(server) as client:
            result: CallToolResult = await client.call_tool(name, arguments)
            return result

    def _runner(
        self, server_id: int, name: str
    ) -> Callable[[ToolContext, dict[str, Any]], Awaitable[ToolResult]]:
        async def run(_context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
            logger.debug("MCP server {} tool {} with {}", server_id, name, arguments)
            try:
                result = await self.call(server_id, name, arguments)
            except Exception as error:
                # No traceback: it could carry the arguments or the request headers.
                logger.warning("MCP tool {} on server {} failed: {}", name, server_id, type(error).__name__)
                return ToolResult(FAILED, ok=False, outcome="failed")
            live = self._live.get(server_id)
            if live is not None:
                live.fetched_at = -LIVE_SECONDS  # The devices just changed.
            return spoken_result(result)

        return run

    def _context_runner(self, server_id: int) -> Callable[[ToolContext], Awaitable[str]]:
        async def run(_context: ToolContext) -> str:
            return await self.live_context(server_id)

        return run

    async def live_context(self, server_id: int) -> str:
        """The device summary of a server, refreshed at most every ``LIVE_SECONDS``. Never raises."""
        live = self._live.get(server_id)
        if live is None:
            return ""
        if time.monotonic() - live.fetched_at < LIVE_SECONDS:
            return live.text
        if live.task is None or live.task.done():
            live.task = asyncio.create_task(self._fetch_live(server_id, live))
        await asyncio.wait({live.task}, timeout=LIVE_WAIT_SECONDS)
        return live.text

    async def _fetch_live(self, server_id: int, live: _Live) -> None:
        server = self._store.mcp_server(server_id)
        text = ""
        try:
            if server is not None:
                result = await self.call(server_id, live.tool, {})
                text = "" if result.is_error else live_summary(server.name, _text(result))
        except Exception as error:
            logger.warning("Device states of MCP server {} unavailable: {}", server_id, type(error).__name__)
        live.text, live.fetched_at = text, time.monotonic()
