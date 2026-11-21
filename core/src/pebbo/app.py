"""HTTP application of the Pebbo core."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import BackgroundTasks, FastAPI
from fastapi.staticfiles import StaticFiles

from pebbo import __version__

if TYPE_CHECKING:
    from pebbo.calendars.sync import CalendarSync
    from pebbo.chat import TextChat
    from pebbo.instances.peers import Peers
    from pebbo.routines.engine import RoutineScheduler
    from pebbo.store import Store
    from pebbo.voice.pipeline import VoiceServices


def create_app(
    voice: "VoiceServices | None" = None,
    web_dist: str | None = None,
    store: "Store | None" = None,
    peers: "Peers | None" = None,
    chat: "TextChat | None" = None,
) -> FastAPI:
    """Create the core application.

    Args:
        voice: Loaded voice services. Without them, no conversations are served.
        web_dist: Directory of the built PC app and control centre to serve at ``/``.
        store: The instance database. With it, the control centre API and the phone app API
            are served.
        peers: The paired other instances. By default they come from the database.
        chat: The text chat for phones. By default it uses the voice services' model.

    The interactive API docs are disabled because they load assets from a public CDN,
    which would break the local-first rule.
    """

    store = store or (voice.store if voice is not None else None)
    routines, calendars = _planning(store, voice)
    integrations = None
    if store is not None:
        from pebbo.tools.mcp import McpTools
        from pebbo.tools.registry import ToolRegistry

        integrations = McpTools(store, voice.registry if voice is not None else ToolRegistry())

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if voice is not None:
            voice.scheduler.start()
            if voice.router is not None:
                await voice.router.start()
        if routines is not None and calendars is not None:
            routines.start()
            calendars.start()
        # Connect to the MCP servers in the background, so a slow one never delays the start.
        connecting = asyncio.create_task(integrations.refresh()) if integrations is not None else None
        yield
        if connecting is not None:
            connecting.cancel()
        if routines is not None and calendars is not None:
            await routines.stop()
            await calendars.stop()
        if voice is not None:
            await voice.scheduler.stop()
            if voice.router is not None:
                await voice.router.stop()

    app = FastAPI(
        title="Pebbo core",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    from pebbo.access import LocalAccess

    app.add_middleware(LocalAccess)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    # Integrations with device states (StateSource) attach to app.state.routines.
    app.state.routines = routines
    if store is not None and integrations is not None and routines is not None and calendars is not None:
        from pebbo.calendars.api import calendar_router
        from pebbo.config import ServerConfig
        from pebbo.control_api import control_router
        from pebbo.devices.gateway import device_router
        from pebbo.instances.api import instance_control_router, peer_router, register_handoff_tool
        from pebbo.instances.peers import Peers
        from pebbo.integrations_api import integrations_router
        from pebbo.routines.api import routines_router

        app.include_router(control_router(store))
        app.include_router(device_router(store))
        app.include_router(integrations_router(store, integrations))
        app.include_router(routines_router(store, routines))
        app.include_router(calendar_router(store, calendars))
        if peers is None:
            config = ServerConfig()
            peers = Peers(store, config.instance_name, config.own_address())
        app.include_router(peer_router(peers))
        app.include_router(instance_control_router(peers))
        from pebbo.chat import TextChat, current_model
        from pebbo.phones import app_router, phone_control_router

        if chat is None:
            registry = voice.registry if voice is not None else None
            chat = TextChat(store, current_model(voice), registry=registry)
        app.include_router(phone_control_router(store, chat))
        app.include_router(app_router(store, chat))
        if voice is not None:
            register_handoff_tool(voice.registry, peers)
            if voice.router is not None:
                from pebbo.compute_api import compute_router

                app.include_router(compute_router(voice.router))
    if voice is not None:
        _add_voice_routes(app, voice)
    if web_dist:
        app.mount("/", StaticFiles(directory=Path(web_dist), html=True), name="web")
    return app


def _planning(
    store: "Store | None", voice: "VoiceServices | None"
) -> "tuple[RoutineScheduler | None, CalendarSync | None]":
    """The routine scheduler and the calendar sync. They need no language model."""
    if store is None:
        return None, None
    from pebbo.calendars.sync import CalendarSync
    from pebbo.routines.engine import RoutineScheduler
    from pebbo.tools import builtin_tools

    registry = voice.registry if voice is not None else builtin_tools()
    speak = voice.scheduler.announce if voice is not None else None
    return RoutineScheduler(store, registry, speak), CalendarSync(store)


def _add_voice_routes(app: FastAPI, voice: "VoiceServices") -> None:
    from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
    from pipecat.transports.smallwebrtc.request_handler import (
        SmallWebRTCPatchRequest,
        SmallWebRTCRequest,
        SmallWebRTCRequestHandler,
    )

    from pebbo.voice.pipeline import run_conversation, webrtc_transport

    # No ICE servers: the browser and the core talk directly on the local network, and
    # aiortc would otherwise fall back to a public STUN server.
    handler = SmallWebRTCRequestHandler(ice_servers=[])

    @app.post("/api/offer")
    async def offer(request: SmallWebRTCRequest, background_tasks: BackgroundTasks) -> dict[str, Any] | None:
        async def on_connection(connection: SmallWebRTCConnection) -> None:
            background_tasks.add_task(run_conversation, webrtc_transport(connection), voice)

        return await handler.handle_web_request(request=request, webrtc_connection_callback=on_connection)

    from fastapi import WebSocket

    from pebbo.devices.gateway import serve_body

    @app.websocket("/xiaozhi/v1/")
    async def body(websocket: WebSocket) -> None:
        await serve_body(websocket, voice)

    @app.patch("/api/offer")
    async def ice_candidate(request: SmallWebRTCPatchRequest) -> dict[str, str]:
        await handler.handle_patch_request(request)
        return {"status": "success"}
