"""Collect the audio of each utterance and identify who spoke it."""

from __future__ import annotations

from collections import deque

import numpy as np
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    Frame,
    InputAudioRawFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from scipy.signal import resample_poly

from pebbo.people.speaker import MIN_SECONDS, SAMPLE_RATE
from pebbo.voice.session import ConversationState

_MAX_SECONDS = 20
# The voice activity detector reports speech only after it has heard some of it, and its
# frame travels back up the pipeline. Keep the audio just before the start as well.
_PRE_ROLL_SECONDS = 1.0


class SpeakerTap(FrameProcessor):
    """Passes all frames on and hands the speech of each user turn to speaker identification.

    A turn often arrives in several short segments ("Hey Pebbo" ... "ich bin Sara"). Short
    segments give weak voice fingerprints, so all segments since Pebbo last spoke are
    identified together. Audio that was too short to identify is kept for the next turn.
    """

    def __init__(self, state: ConversationState) -> None:
        super().__init__()
        self._state = state
        self._chunks: list[np.ndarray] = []
        self._pre_roll: deque[np.ndarray] = deque()
        self._rate = SAMPLE_RATE
        self._collecting = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, BotStartedSpeakingFrame):
            if self._collected() >= self._rate * MIN_SECONDS:
                self._chunks = []
        elif isinstance(frame, VADUserStartedSpeakingFrame) and not self._collecting:
            self._collecting = True
            self._chunks.extend(self._pre_roll)
            self._pre_roll.clear()
        elif isinstance(frame, VADUserStoppedSpeakingFrame) and self._collecting:
            self._collecting = False
            samples = self._samples()
            if len(samples):
                self._state.identify_in_background(samples)
        elif isinstance(frame, InputAudioRawFrame):
            self._rate = frame.sample_rate
            self._add(np.frombuffer(frame.audio, dtype=np.int16))
        await self.push_frame(frame, direction)

    def _add(self, chunk: np.ndarray) -> None:
        if self._collecting:
            self._chunks.append(chunk)
            while self._collected() > self._rate * _MAX_SECONDS:
                self._chunks.pop(0)
            return
        self._pre_roll.append(chunk)
        while sum(len(c) for c in self._pre_roll) > self._rate * _PRE_ROLL_SECONDS:
            self._pre_roll.popleft()

    def _collected(self) -> int:
        return sum(len(chunk) for chunk in self._chunks)

    def _samples(self) -> np.ndarray:
        if not self._chunks:
            return np.zeros(0, dtype=np.float32)
        audio = np.concatenate(self._chunks).astype(np.float32) / 32768.0
        if self._rate != SAMPLE_RATE:
            audio = resample_poly(audio, SAMPLE_RATE, self._rate)
        return audio.astype(np.float32)
