"""Make Pebbo's voice a little higher and quicker, which sounds cuter.

The synthesised audio is read faster than it was recorded, which raises the pitch and the
tempo by the same factor. A small streaming interpolator keeps the chunk borders free of
clicks.
"""

from __future__ import annotations

import dataclasses

import numpy as np
from pipecat.frames.frames import Frame, InterruptionFrame, TTSAudioRawFrame, TTSStartedFrame, TTSStoppedFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class StreamingSpeedup:
    """Reads a stream of samples ``factor`` times faster, using linear interpolation."""

    def __init__(self, factor: float) -> None:
        self._factor = factor
        self._position = 0.0  # Read position relative to the first sample of the buffer.
        self._buffer = np.zeros(0, dtype=np.float32)

    def process(self, chunk: np.ndarray) -> np.ndarray:
        self._buffer = np.concatenate([self._buffer, chunk.astype(np.float32)])
        available = len(self._buffer) - 1
        if available <= self._position:
            return np.zeros(0, dtype=np.int16)
        positions = np.arange(self._position, available, self._factor)
        output = np.interp(positions, np.arange(len(self._buffer)), self._buffer)
        self._position = positions[-1] + self._factor
        consumed = int(self._position)
        self._buffer = self._buffer[consumed:]
        self._position -= consumed
        result: np.ndarray = np.clip(np.round(output), -32768, 32767).astype(np.int16)
        return result


class PitchShifter(FrameProcessor):
    """Raises pitch and tempo of the synthesised voice by ``factor`` (1.0 leaves it unchanged)."""

    def __init__(self, factor: float) -> None:
        super().__init__()
        self._factor = factor
        self._stream: StreamingSpeedup | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if self._factor == 1.0:
            await self.push_frame(frame, direction)
        elif isinstance(frame, TTSAudioRawFrame) and frame.num_channels == 1:
            await self._shift(frame, direction)
        elif isinstance(frame, (TTSStartedFrame, TTSStoppedFrame, InterruptionFrame)):
            self._stream = None
            await self.push_frame(frame, direction)
        else:
            await self.push_frame(frame, direction)

    async def _shift(self, frame: TTSAudioRawFrame, direction: FrameDirection) -> None:
        if self._stream is None:
            self._stream = StreamingSpeedup(self._factor)
        samples = self._stream.process(np.frombuffer(frame.audio, dtype=np.int16))
        if len(samples):
            await self.push_frame(self._copy(frame, samples), direction)

    @staticmethod
    def _copy(frame: TTSAudioRawFrame, samples: np.ndarray) -> TTSAudioRawFrame:
        return dataclasses.replace(frame, audio=samples.astype(np.int16).tobytes())
