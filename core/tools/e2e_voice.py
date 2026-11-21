"""End-to-end voice test against a running ``pebbo serve``.

Plays a script of spoken clips into Pebbo over WebRTC, like a browser would, records what
Pebbo says and logs the events it sends. Used to test conversations without a microphone.

Usage:
    uv run python tools/e2e_voice.py SCRIPT.json [--url http://127.0.0.1:8100] [--out reply.wav]

SCRIPT.json is a list of steps: {"at": seconds, "clip": "path.wav"} or {"at": seconds, "end": true}.
"""

from __future__ import annotations

import argparse
import asyncio
import fractions
import json
import time
import uuid
import wave
from collections.abc import Callable
from pathlib import Path

import aiohttp
import numpy as np
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from av import AudioFrame
from scipy.signal import resample_poly

RATE = 48_000
FRAME = 960  # 20 ms


def load_clip(path: str) -> np.ndarray:
    with wave.open(path) as clip:
        samples = np.frombuffer(clip.readframes(clip.getnframes()), dtype=np.int16).astype(np.float32)
        rate = clip.getframerate()
    return resample_poly(samples, RATE, rate).astype(np.int16)


class ScriptedMicrophone(MediaStreamTrack):
    """An audio track that plays clips at scheduled times and silence otherwise."""

    kind = "audio"

    def __init__(self, steps: list[tuple[float, np.ndarray]], log: Callable[[str], None]) -> None:
        super().__init__()
        self._log = log
        self._steps = sorted(steps, key=lambda step: step[0])
        self._start: float | None = None
        self._sent = 0
        self._playing: np.ndarray | None = None
        self._position = 0

    async def recv(self) -> AudioFrame:
        if self._start is None:
            self._start = time.monotonic()
        due = self._start + self._sent * FRAME / RATE
        await asyncio.sleep(max(0.0, due - time.monotonic()))
        elapsed = self._sent * FRAME / RATE
        if self._playing is None and self._steps and self._steps[0][0] <= elapsed:
            self._playing, self._position = self._steps.pop(0)[1], 0
            self._log(f"clip starts ({len(self._playing) / RATE:.2f}s)")
        chunk = np.zeros(FRAME, dtype=np.int16)
        if self._playing is not None:
            part = self._playing[self._position : self._position + FRAME]
            chunk[: len(part)] = part
            self._position += FRAME
            if self._position >= len(self._playing):
                self._playing = None
                self._log("clip ends")
        frame = AudioFrame.from_ndarray(chunk.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate, frame.pts, frame.time_base = RATE, self._sent * FRAME, fractions.Fraction(1, RATE)
        self._sent += 1
        return frame


async def run(script: list[dict[str, object]], url: str, out: str) -> None:
    steps = [(float(step["at"]), load_clip(str(step["clip"]))) for step in script if "clip" in step]  # type: ignore[arg-type]
    end_at = max(float(step["at"]) for step in script)  # type: ignore[arg-type]
    pc = RTCPeerConnection()
    pc.addTrack(ScriptedMicrophone(steps, lambda message: print(stamp(), message)))
    channel = pc.createDataChannel("pipecat")
    received: list[np.ndarray] = []
    channels: list[int] = []
    recorders: list[asyncio.Future[None]] = []
    started = time.monotonic()

    def stamp() -> str:
        return f"[{time.monotonic() - started:6.2f}s]"

    @channel.on("open")
    def on_open() -> None:
        channel.send(
            json.dumps(
                {
                    "label": "rtvi-ai",
                    "type": "client-ready",
                    "id": str(uuid.uuid4()),
                    "data": {"version": "2.3.0", "about": {"library": "pebbo-e2e"}},
                }
            )
        )

    @channel.on("message")
    def on_message(message: str) -> None:
        try:
            data = json.loads(message)
        except (TypeError, ValueError):
            return
        kind = data.get("type")
        if kind in {
            "user-started-speaking",
            "user-stopped-speaking",
            "bot-started-speaking",
            "bot-stopped-speaking",
            "bot-llm-started",
            "bot-ready",
        }:
            print(stamp(), kind)
        elif kind == "user-transcription" and data.get("data", {}).get("final"):
            print(stamp(), "heard:", data["data"].get("text"))
        elif kind == "bot-output" or kind == "bot-tts-text":
            text = data.get("data", {}).get("text")
            if text:
                print(stamp(), "says:", text)
        elif kind == "server-message":
            print(stamp(), "server:", data.get("data"))

    @pc.on("track")
    def on_track(track: MediaStreamTrack) -> None:
        async def record() -> None:
            while True:
                try:
                    frame = await track.recv()
                except Exception:
                    return
                channels.append(len(frame.layout.channels))
                received.append(frame.to_ndarray().flatten())

        recorders.append(asyncio.ensure_future(record()))

    await pc.setLocalDescription(await pc.createOffer())
    async with aiohttp.ClientSession() as session:
        response = await session.post(
            f"{url}/api/offer", json={"sdp": pc.localDescription.sdp, "type": "offer"}
        )
        answer = await response.json()
    await pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type=answer["type"]))
    await asyncio.sleep(end_at)
    await pc.close()
    if received:
        audio = np.concatenate(received).astype(np.int16)
        with wave.open(out, "wb") as recording:
            recording.setnchannels(channels[0])
            recording.setsampwidth(2)
            recording.setframerate(RATE)
            recording.writeframes(audio.tobytes())
        print(f"Recorded {len(audio) / RATE / channels[0]:.1f}s of Pebbo's audio to {out}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("script")
    parser.add_argument("--url", default="http://127.0.0.1:8100")
    parser.add_argument("--out", default="pebbo-reply.wav")
    arguments = parser.parse_args()
    asyncio.run(
        run(json.loads(Path(arguments.script).read_text(encoding="utf-8")), arguments.url, arguments.out)
    )


if __name__ == "__main__":
    main()
