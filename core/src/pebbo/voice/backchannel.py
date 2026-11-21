"""Tell interruptions from backchannels while Pebbo is speaking.

People say "mhm", "ja" or "genau" while listening. Those must not stop Pebbo. A stop word
or real content must stop it at once. Pebbo's own voice leaking into the microphone must be
ignored as well.
"""

from __future__ import annotations

import enum
import re
import time
from collections import deque

from loguru import logger
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
)
from pipecat.turns.user_start.base_user_turn_start_strategy import BaseUserTurnStartStrategy

from pebbo.voice.wake import is_sleep_command

BACKCHANNELS = frozenset(
    {
        "mhm",
        "mh",
        "hm",
        "hmm",
        "mm",
        "aha",
        "ah",
        "oh",
        "ja",
        "jaja",
        "jo",
        "genau",
        "okay",
        "ok",
        "klar",
        "stimmt",
        "richtig",
        "achso",
        "ach",
        "so",
        "cool",
        "super",
        "gut",
        "nice",
        "wow",
        "echt",
        "krass",
        "voll",
        "jep",
        "yes",
        "yeah",
        "mhmh",
        "uh",
        "äh",
        "ähm",
        "hmhm",
        "na",
    }
)
STOP_WORDS = frozenset(
    {"stopp", "stop", "halt", "warte", "moment", "ruhe", "still", "aufhören", "pause", "nein"}
)

_WORD = re.compile(r"[\wäöüß]+", re.IGNORECASE)


class Utterance(enum.Enum):
    """How a transcript heard while Pebbo speaks should be treated."""

    BACKCHANNEL = "backchannel"
    STOP = "stop"
    CONTENT = "content"
    ECHO = "echo"


def words(text: str) -> list[str]:
    """Split a transcript into lower-case words."""
    return [word.lower() for word in _WORD.findall(text)]


def classify(text: str, recent_bot_words: set[str] | None = None) -> Utterance:
    """Classify a transcript that arrived while Pebbo was speaking.

    Args:
        text: The transcript.
        recent_bot_words: Words Pebbo spoke in the last seconds, to detect its own echo.
    """
    tokens = words(text)
    if not tokens:
        return Utterance.BACKCHANNEL
    if any(token in STOP_WORDS for token in tokens):
        return Utterance.STOP
    content = [token for token in tokens if token not in BACKCHANNELS]
    if not content:
        return Utterance.BACKCHANNEL
    if recent_bot_words and len(content) >= 2:
        overlap = sum(token in recent_bot_words for token in content) / len(content)
        if overlap >= 0.7:
            return Utterance.ECHO
    if len(content) >= 2:
        return Utterance.CONTENT
    return Utterance.BACKCHANNEL


class SpokenTextMemory:
    """Remembers what Pebbo said recently, to recognise its own voice as echo."""

    def __init__(self, window_seconds: float = 8.0) -> None:
        self._window = window_seconds
        self._entries: deque[tuple[float, str]] = deque()

    def add(self, text: str) -> None:
        now = time.monotonic()
        self._entries.append((now, text))
        self._forget(now)

    def recent_words(self) -> set[str]:
        self._forget(time.monotonic())
        return {word for _, text in self._entries for word in words(text)}

    def _forget(self, now: float) -> None:
        while self._entries and now - self._entries[0][0] > self._window:
            self._entries.popleft()


class BackchannelAwareTurnStartStrategy(BaseUserTurnStartStrategy):
    """Start a user turn from transcripts, ignoring backchannels and echo while Pebbo is busy.

    Pebbo counts as busy while it speaks and while it prepares a reply, which ends when it
    starts speaking or after ``reply_wait_seconds``. A plain "ja" outside that window is a
    real answer, for example to a question Pebbo asked.
    """

    def __init__(
        self, *, spoken: SpokenTextMemory, reply_wait_seconds: float = 8.0, **kwargs: object
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._spoken = spoken
        self._reply_wait = reply_wait_seconds
        self._bot_speaking = False
        self._awaiting_reply_until = 0.0

    @property
    def busy(self) -> bool:
        return self._bot_speaking or time.monotonic() < self._awaiting_reply_until

    async def handle_user_turn_started(self) -> None:
        self._bot_speaking = False

    async def handle_user_turn_stopped(self) -> None:
        self._awaiting_reply_until = time.monotonic() + self._reply_wait

    async def process_frame(self, frame: Frame) -> None:
        if isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking, self._awaiting_reply_until = True, 0.0
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
        elif isinstance(frame, TranscriptionFrame) and not isinstance(frame, InterimTranscriptionFrame):
            await self._handle_transcription(frame.text)

    async def _handle_transcription(self, text: str) -> None:
        if is_sleep_command(text):
            await self.trigger_reset_aggregation()  # PebboWakeStrategy ends the conversation.
            return
        if not self.busy:
            if words(text):
                await self.report_user_turn_started()
            return
        kind = classify(text, self._spoken.recent_words())
        logger.debug("Heard while busy: {}", kind.value)
        if kind in (Utterance.STOP, Utterance.CONTENT):
            await self.report_user_turn_started()
        else:
            await self.trigger_reset_aggregation()
