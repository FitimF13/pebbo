"""Pebbo bodies: ESP32-S3 devices running the open xiaozhi-esp32 firmware.

The firmware asks an OTA address at boot where to connect. Pebbo answers that address
itself, so a body talks only to the local core:

1. ``POST /xiaozhi/ota/``: an unpaired body gets a six-digit pairing code, which it shows
   and speaks. The owner enters the code in the control centre. A paired body gets the
   WebSocket address and its own token instead.
2. ``POST /xiaozhi/ota/activate``: the body asks whether the code was entered yet.
3. ``WS /xiaozhi/v1/``: the conversation. The body streams 16 kHz Opus from its
   microphone (with echo cancellation on the device) and plays 24 kHz Opus from Pebbo.
   The same voice pipeline as for the PC app runs on it.

Protocol details: docs/devices.md.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import secrets
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from loguru import logger
from pipecat.frames.frames import Frame, InputAudioRawFrame, InterruptionFrame, OutputAudioRawFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.serializers.base_serializer import FrameSerializer
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketOutputTransport,
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from pebbo import clock
from pebbo.devices.opus import OpusDecoder, OpusEncoder
from pebbo.store import Device, Store

if TYPE_CHECKING:
    from pebbo.voice.pipeline import VoiceServices

PAIRING_CODE_SECONDS = 10 * 60
INPUT_RATE = 16_000
OUTPUT_RATE = 24_000
# The firmware waits this long for the server's hello.
_HELLO_TIMEOUT_SECONDS = 10.0
# After this much silence from the speech synthesis, Pebbo's turn on the body is over.
_SPEECH_END_SECONDS = 0.8
# Pebbo's emotions as the firmware's emotion names, which select the face on the screen.
FACES = {
    "happy": "happy",
    "laughing": "laughing",
    "surprised": "surprised",
    "sad": "sad",
    "embarrassed": "embarrassed",
    "sulky": "angry",
    "proud": "confident",
    "curious": "winking",
    "neutral": "neutral",
    "thinking": "thinking",
    "asleep": "sleepy",
    "awake": "happy",
}

Events = Callable[[dict[str, str]], Awaitable[None]]


def _server_time() -> dict[str, int]:
    now = datetime.now(clock.timezone())
    offset = now.utcoffset()
    return {
        "timestamp": int(now.timestamp() * 1000),
        "timezone_offset": int(offset.total_seconds() // 60) if offset else 0,
    }


def _bearer(value: str) -> str:
    return value.split(" ", 1)[1].strip() if value.lower().startswith("bearer ") else value.strip()


def _new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def device_router(store: Store) -> APIRouter:
    """The boot-time endpoints of the firmware: where to connect, and pairing."""
    router = APIRouter(prefix="/xiaozhi")

    def identity(request: Request) -> tuple[str, str]:
        return request.headers.get("device-id", "").lower(), request.headers.get("client-id", "")

    @router.api_route("/ota/", methods=["GET", "POST"])
    async def ota(request: Request) -> Response:
        device_id, client_id = identity(request)
        if not device_id or not client_id:
            return JSONResponse({"error": "Device-Id and Client-Id are required"}, status_code=400)
        info: dict[str, Any] = {}
        if request.method == "POST":
            try:
                info = json.loads(await request.body() or b"{}")
            except json.JSONDecodeError:
                info = {}
        version = str(info.get("application", {}).get("version", "0.0.0"))
        reply: dict[str, Any] = {"server_time": _server_time(), "firmware": {"version": version, "url": ""}}
        device = store.device(device_id, client_id)
        if device is not None and device.status == "paired" and device.token:
            store.touch_device(device.id)
            host = request.url.hostname or "localhost"
            port = request.url.port or (443 if request.url.scheme == "https" else 80)
            scheme = "wss" if request.url.scheme == "https" else "ws"
            reply["websocket"] = {
                "url": f"{scheme}://{host}:{port}/xiaozhi/v1/",
                "token": device.token,
                "version": 1,
            }
            return JSONResponse(reply)
        board = str(info.get("board", {}).get("name") or request.headers.get("user-agent", "")).split("/")[0]
        now = time.time()
        if device is not None and device.pairing_code and (device.code_expires_at or 0) > now + 60:
            code = device.pairing_code
        else:
            code = _new_code()
            store.request_pairing(device_id, client_id, board or "unknown", code, now + PAIRING_CODE_SECONDS)
            logger.info("A new Pebbo body asks to be paired")
        reply["activation"] = {
            "code": code,
            "message": "Gib diesen Code im Kontrollzentrum unter Geräte ein.",
            "timeout_ms": PAIRING_CODE_SECONDS * 1000,
        }
        return JSONResponse(reply)

    @router.post("/ota/activate")
    async def activate(request: Request) -> Response:
        device = store.device(*identity(request))
        if device is not None and device.status == "paired":
            return JSONResponse({"status": "paired"})
        return JSONResponse({"status": "pending"}, status_code=202)

    return router


# Bodies connected right now, by device row id.
_CONNECTED: dict[int, WebSocket] = {}


def is_online(device_id: int) -> bool:
    return device_id in _CONNECTED


async def disconnect(device_id: int) -> None:
    """Close a removed body's connection at once. It must pair again to come back."""
    websocket = _CONNECTED.pop(device_id, None)
    if websocket is not None:
        with contextlib.suppress(RuntimeError):
            await websocket.close(code=4401)


def pair(store: Store, code: str) -> Device | None:
    """Pair the body that shows this code. Called from the control centre."""
    device = store.pair_device(code, secrets.token_urlsafe(32))
    if device is not None:
        logger.info("Pebbo body {} paired", device.id)
    return device


class XiaozhiSerializer(FrameSerializer):
    """Turns the body's Opus packets into audio frames and its JSON messages into callbacks."""

    def __init__(self, on_message: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        super().__init__()
        self._decoder = OpusDecoder(INPUT_RATE)
        self._on_message = on_message

    async def serialize(self, frame: Frame) -> str | bytes | None:
        # The output transport encodes audio itself, see BodyOutputTransport.
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        if isinstance(data, bytes):
            pcm = self._decoder.decode(data)
            return InputAudioRawFrame(audio=pcm, sample_rate=INPUT_RATE, num_channels=1) if pcm else None
        try:
            message = json.loads(data)
        except json.JSONDecodeError:
            return None
        if isinstance(message, dict):
            await self._on_message(message)
        return None


class BodyOutputTransport(FastAPIWebsocketOutputTransport):
    """Sends Pebbo's speech as 60 ms Opus packets, framed by the firmware's tts messages.

    The firmware plays audio only between ``tts start`` and ``tts stop``, so the start is
    sent before the first packet of each answer and the stop after a short silence.
    """

    def __init__(
        self, *args: Any, send_json: Callable[[dict[str, Any]], Awaitable[None]], **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self._encoder = OpusEncoder(OUTPUT_RATE)
        self._send_json = send_json
        self._speaking = False
        self._last_audio = 0.0
        self._watch: asyncio.Task[None] | None = None

    async def write_audio_frame(self, frame: OutputAudioRawFrame) -> bool:
        if self._client.is_closing or not self._client.is_connected:
            return False
        if not self._speaking:
            self._speaking = True
            await self._send_json({"type": "tts", "state": "start"})
            # The firmware switches state on its main task; give it a moment before audio.
            await asyncio.sleep(0.05)
            self._watch = self.create_task(self._watch_for_end())
        self._last_audio = time.monotonic()
        for packet in self._encoder.encode(frame.audio):
            await self._client.send(packet)
        await self._write_audio_sleep()
        return True

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, InterruptionFrame):
            self._encoder.clear()
            await self._end_speech(flush=False)

    async def _watch_for_end(self) -> None:
        while self._speaking:
            await asyncio.sleep(0.1)
            if time.monotonic() - self._last_audio > _SPEECH_END_SECONDS:
                await self._end_speech(flush=True)

    async def _end_speech(self, *, flush: bool) -> None:
        if not self._speaking:
            return
        self._speaking = False
        if flush and self._client.is_connected:
            for packet in self._encoder.flush():
                await self._client.send(packet)
        if self._client.is_connected:
            await self._send_json({"type": "tts", "state": "stop"})


class BodyTransport(FastAPIWebsocketTransport):
    """A Pipecat transport for one connected body."""

    def __init__(self, websocket: WebSocket, on_message: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        params = FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=INPUT_RATE,
            audio_out_sample_rate=OUTPUT_RATE,
            serializer=XiaozhiSerializer(on_message),
        )
        super().__init__(websocket, params)
        self._output = BodyOutputTransport(self, self._client, self._params, send_json=self.send_json)
        self._websocket = websocket
        self._lock = asyncio.Lock()

    async def send_json(self, message: dict[str, Any]) -> None:
        async with self._lock:
            try:
                await self._client.send(json.dumps(message, ensure_ascii=False))
            except Exception as error:  # The body went away; the pipeline notices on its own.
                logger.debug("Could not send to the body: {}", error)


async def serve_body(websocket: WebSocket, voice: VoiceServices) -> None:
    """Accept a paired body and run Pebbo's conversation pipeline on it."""
    from pebbo.voice.pipeline import run_conversation

    store = voice.store
    device = store.device_by_token(_bearer(websocket.headers.get("authorization", "")))
    if device is None or device.device_id != websocket.headers.get("device-id", "").lower():
        logger.info("A body without a valid pairing tried to connect")
        await websocket.close(code=4401)
        return
    await websocket.accept()
    try:
        hello = json.loads(await asyncio.wait_for(websocket.receive_text(), _HELLO_TIMEOUT_SECONDS))
    except (TimeoutError, WebSocketDisconnect, json.JSONDecodeError):
        await websocket.close()
        return
    if not isinstance(hello, dict) or hello.get("type") != "hello":
        await websocket.close()
        return
    session = str(uuid.uuid4())
    await websocket.send_text(
        json.dumps(
            {
                "type": "hello",
                "transport": "websocket",
                "session_id": session,
                "audio_params": {
                    "format": "opus",
                    "sample_rate": OUTPUT_RATE,
                    "channels": 1,
                    "frame_duration": 60,
                },
            }
        )
    )
    store.touch_device(device.id)
    logger.info("Pebbo body {} connected", device.id)
    wake: list[Callable[[], Awaitable[None]]] = []

    async def on_message(message: dict[str, Any]) -> None:
        kind, state = message.get("type"), message.get("state")
        if kind == "listen" and state == "detect":
            # The body's own wake word fired.
            for handler in wake:
                await handler()
        elif kind == "abort":
            await transport.send_json({"type": "tts", "state": "stop"})

    transport = BodyTransport(websocket, on_message)

    async def events(data: dict[str, str]) -> None:
        face = FACES.get(data.get("emotion") or data.get("state") or "")
        if face:
            await transport.send_json({"type": "llm", "emotion": face})

    _CONNECTED[device.id] = websocket
    try:
        await run_conversation(transport, voice, events=events, on_wake_handler=wake.append)
    finally:
        if _CONNECTED.get(device.id) is websocket:
            del _CONNECTED[device.id]
        store.touch_device(device.id)
    logger.info("Pebbo body {} disconnected", device.id)
