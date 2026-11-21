"""Simulate a Pebbo body against a running ``pebbo serve``, like the ESP32-S3 firmware does.

Runs the whole device path without hardware: the boot-time OTA request, pairing with the
code (entered through the control centre API when ``--pair`` is given), the WebSocket
handshake, 60 ms Opus packets from the microphone and Opus playback of Pebbo's answers.

Usage:
    uv run python tools/device_sim.py SCRIPT.json [--url http://127.0.0.1:8100] [--pair] [--out reply.wav]

SCRIPT.json is the same as for tools/e2e_voice.py: {"at": seconds, "clip": "path.wav"} steps and
a final {"at": seconds, "end": true}.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import wave
from pathlib import Path

import aiohttp
import numpy as np
from scipy.signal import resample_poly

from pebbo.devices.opus import OpusDecoder, OpusEncoder

MIC_RATE = 16_000
PACKET = MIC_RATE * 60 // 1000
HEADERS = {
    "Device-Id": "aa:bb:cc:00:11:22",
    "Client-Id": "6f1c7a52-0b8e-4a39-9d1e-0a1b2c3d4e5f",
    "User-Agent": "esp-box-3/2.6.0",
    "Accept-Language": "de-DE",
}
BOOT_INFO = {
    "version": 2,
    "language": "de-DE",
    "application": {"name": "xiaozhi", "version": "2.6.0"},
    "board": {"type": "esp-box-3", "name": "esp-box-3"},
}


def load_clip(path: str) -> np.ndarray:
    with wave.open(path) as clip:
        samples = np.frombuffer(clip.readframes(clip.getnframes()), dtype=np.int16).astype(np.float32)
        rate = clip.getframerate()
    return resample_poly(samples, MIC_RATE, rate).astype(np.int16)


async def boot(session: aiohttp.ClientSession, url: str, pair: bool) -> dict[str, str]:
    """Do what the firmware does at boot until it knows where to connect."""
    for _ in range(3):
        async with session.post(f"{url}/xiaozhi/ota/", json=BOOT_INFO, headers=HEADERS) as response:
            reply = await response.json()
        if "websocket" in reply:
            return dict(reply["websocket"])
        code = reply["activation"]["code"]
        print(f"Pairing code on the screen: {code}")
        if not pair:
            raise SystemExit("Enter the code in the control centre, or run with --pair.")
        async with session.post(f"{url}/api/control/devices/pair", json={"code": code}) as response:
            response.raise_for_status()
        async with session.post(f"{url}/xiaozhi/ota/activate", json={}, headers=HEADERS) as response:
            print("Activation:", response.status)
    raise SystemExit("The core never sent a WebSocket address.")


async def run(script_path: str, url: str, pair: bool, out: str | None) -> None:
    steps = json.loads(Path(script_path).read_text(encoding="utf-8"))
    clips = [(float(step["at"]), load_clip(step["clip"])) for step in steps if "clip" in step]
    end = max(float(step["at"]) for step in steps)
    encoder = OpusEncoder(MIC_RATE)
    decoder = OpusDecoder(16_000)
    received = bytearray()
    start = time.monotonic()

    def log(message: str) -> None:
        print(f"[{time.monotonic() - start:6.2f}s] {message}")

    async with aiohttp.ClientSession() as session:
        websocket_config = await boot(session, url, pair)
        headers = {**HEADERS, "Authorization": f"Bearer {websocket_config['token']}", "Protocol-Version": "1"}
        async with session.ws_connect(websocket_config["url"], headers=headers) as ws:
            await ws.send_str(
                json.dumps(
                    {
                        "type": "hello",
                        "version": 1,
                        "features": {"mcp": True},
                        "transport": "websocket",
                        "audio_params": {
                            "format": "opus",
                            "sample_rate": 16000,
                            "channels": 1,
                            "frame_duration": 60,
                        },
                    }
                )
            )
            hello = json.loads((await ws.receive()).data)
            log(f"server hello: {hello.get('audio_params')}")
            await ws.send_str(
                json.dumps(
                    {
                        "session_id": hello["session_id"],
                        "type": "listen",
                        "state": "start",
                        "mode": "realtime",
                    }
                )
            )

            async def microphone() -> None:
                sent = 0
                queue = sorted(clips, key=lambda clip: clip[0])
                playing: np.ndarray | None = None
                position = 0
                while sent * PACKET / MIC_RATE < end:
                    due = start + sent * PACKET / MIC_RATE
                    await asyncio.sleep(max(0.0, due - time.monotonic()))
                    elapsed = sent * PACKET / MIC_RATE
                    if playing is None and queue and queue[0][0] <= elapsed:
                        playing, position = queue.pop(0)[1], 0
                        log("clip starts")
                    chunk = np.zeros(PACKET, dtype=np.int16)
                    if playing is not None:
                        part = playing[position : position + PACKET]
                        chunk[: len(part)] = part
                        position += PACKET
                        if position >= len(playing):
                            playing = None
                    for packet in encoder.encode(chunk.tobytes()):
                        await ws.send_bytes(packet)
                    sent += 1
                await ws.close()

            async def speaker() -> None:
                async for message in ws:
                    if message.type == aiohttp.WSMsgType.BINARY:
                        received.extend(decoder.decode(message.data))
                    elif message.type == aiohttp.WSMsgType.TEXT:
                        log(f"server: {message.data}")

            await asyncio.gather(microphone(), speaker())
    seconds = len(received) / 2 / 16_000
    log(f"received {seconds:.1f} s of Pebbo's speech")
    if out:
        with wave.open(out, "wb") as file:
            file.setnchannels(1)
            file.setsampwidth(2)
            file.setframerate(16_000)
            file.writeframes(bytes(received))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("script")
    parser.add_argument("--url", default="http://127.0.0.1:8100")
    parser.add_argument(
        "--pair", action="store_true", help="enter the pairing code through the control centre API"
    )
    parser.add_argument("--out", help="write Pebbo's speech to this WAV file")
    arguments = parser.parse_args()
    asyncio.run(run(arguments.script, arguments.url, arguments.pair, arguments.out))


if __name__ == "__main__":
    main()
