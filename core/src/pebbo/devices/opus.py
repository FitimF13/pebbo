"""Opus audio for Pebbo bodies, which send and receive 60 ms Opus packets."""

from __future__ import annotations

import fractions
from typing import Any

import av
import numpy as np

FRAME_MS = 60


class OpusDecoder:
    """Decodes Opus packets from a body to 16-bit mono PCM at the pipeline's rate."""

    def __init__(self, sample_rate: int = 16_000) -> None:
        self._codec: Any = av.CodecContext.create("libopus", "r")
        self._resampler = av.AudioResampler(format="s16", layout="mono", rate=sample_rate)

    def decode(self, packet: bytes) -> bytes:
        pcm = bytearray()
        try:
            frames = self._codec.decode(av.Packet(packet))
        except av.error.InvalidDataError:
            return b""
        for frame in frames:
            for resampled in self._resampler.resample(frame):
                pcm += resampled.to_ndarray().astype(np.int16).tobytes()
        return bytes(pcm)


class OpusEncoder:
    """Encodes 16-bit mono PCM into 60 ms Opus packets for a body."""

    def __init__(self, sample_rate: int = 24_000, bitrate: int = 32_000) -> None:
        self.sample_rate = sample_rate
        self.samples_per_packet = sample_rate * FRAME_MS // 1000
        self._buffer = bytearray()
        self._pts = 0
        self._codec: Any = self._open(bitrate)

    def _open(self, bitrate: int) -> Any:
        codec: Any = av.CodecContext.create("libopus", "w")
        codec.sample_rate = self.sample_rate
        codec.layout = "mono"
        codec.format = "s16"
        codec.bit_rate = bitrate
        codec.options = {"frame_duration": str(FRAME_MS), "application": "voip"}
        codec.open()
        return codec

    @property
    def buffered(self) -> int:
        """Samples waiting for a full packet."""
        return len(self._buffer) // 2

    def encode(self, pcm: bytes) -> list[bytes]:
        """Add PCM and return every full packet it completes."""
        self._buffer += pcm
        packets: list[bytes] = []
        size = self.samples_per_packet * 2
        while len(self._buffer) >= size:
            chunk = bytes(self._buffer[:size])
            del self._buffer[:size]
            packets += self._encode_chunk(chunk)
        return packets

    def flush(self) -> list[bytes]:
        """Pad what is left with silence to one last packet."""
        if not self._buffer:
            return []
        missing = self.samples_per_packet * 2 - len(self._buffer)
        return self.encode(b"\x00" * missing)

    def clear(self) -> None:
        self._buffer.clear()

    def _encode_chunk(self, chunk: bytes) -> list[bytes]:
        samples = np.frombuffer(chunk, dtype=np.int16).reshape(1, -1)
        frame = av.AudioFrame.from_ndarray(samples, format="s16", layout="mono")
        frame.sample_rate = self.sample_rate
        frame.pts = self._pts
        frame.time_base = fractions.Fraction(1, self.sample_rate)
        self._pts += self.samples_per_packet
        return [bytes(packet) for packet in self._codec.encode(frame)]
