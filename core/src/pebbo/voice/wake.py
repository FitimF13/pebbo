"""Detect "Hey Pebbo" in transcripts.

Speech recognition spells the made-up name in many ways ("Pebo", "Bebo", "Pecco") and often
drops the "Hey". Pebbo therefore wakes up when its name, compared phonetically, is among the
first words of a transcript.
"""

from __future__ import annotations

import re
import time
from difflib import SequenceMatcher

from loguru import logger
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InterruptionFrame,
    TranscriptionFrame,
)
from pipecat.turns.types import ProcessFrameResult
from pipecat.turns.user_start.wake_phrase_user_turn_start_strategy import (
    WakePhraseUserTurnStartStrategy,
    _WakeState,
)

NAME = "pebbo"
KNOWN_SPELLINGS = frozenset(
    {
        "pebbo",
        "pebo",
        "peppo",
        "pepo",
        "bebo",
        "bebbo",
        "pebbu",
        "pebble",
        "pebbles",
        "peco",
        "people",
        "peppel",
        "beppo",
    }
)
GREETINGS = frozenset({"hey", "hei", "hi", "hallo", "he", "ey", "hoi", "ok", "okay"})
# Biases Whisper towards the name. It can make Whisper hear "Bebbo" in a lone "mhm", which
# is why a name on its own never wakes Pebbo (see addresses_pebbo).
RECOGNITION_HOTWORDS = "Pebbo"

_SIMILARITY = 0.72
_SEARCH_WORDS = 3
# Speech recognition sometimes splits the name into two short words, such as "Pei Bo".
_SPLIT_PART = 4
_WORD = re.compile(r"[a-zäöüß]+")
_PHONETIC = (
    ("ph", "f"),
    ("ck", "k"),
    ("b", "p"),
    ("d", "t"),
    ("g", "k"),
    ("c", "k"),
    ("q", "k"),
    ("u", "o"),
    ("ä", "e"),
    ("y", "i"),
)


def phonetic(word: str) -> str:
    """Reduce a word to a rough sound representation, for example "Pecco" to "peko"."""
    word = word.lower()
    for source, target in _PHONETIC:
        word = word.replace(source, target)
    return re.sub(r"(.)\1+", r"\1", word)


def is_name(word: str) -> bool:
    """Return whether a single word sounds like "Pebbo"."""
    word = word.lower()
    if word in KNOWN_SPELLINGS:
        return True
    return SequenceMatcher(None, phonetic(word), phonetic(NAME)).ratio() >= _SIMILARITY


_FUSED_GREETINGS = ("hei", "hai", "ei", "ai", "he", "hi")


def greeting_with_name(token: str) -> bool:
    """Return whether one word is a greeting and the name run together, such as "Eipepo"."""
    return any(
        token.startswith(greeting) and len(token) - len(greeting) >= 3 and is_name(token[len(greeting) :])
        for greeting in _FUSED_GREETINGS
    )


def addresses_pebbo(text: str) -> bool:
    """Return whether a transcript starts by addressing Pebbo.

    The name must come with a greeting ("Hey Pebbo") or be followed by at least two more
    words ("Pebbo, wie spät ist es?"). A lone name is ignored, because speech recognition
    sometimes hears it in short sounds such as "mhm".
    """
    tokens = _WORD.findall(text.lower())
    for index, token in enumerate(tokens[: _SEARCH_WORDS + 1]):
        if index == 0 and greeting_with_name(token):
            return True
        length = _name_length(tokens, index)
        if not length:
            continue
        greeted = any(word in GREETINGS for word in tokens[:index])
        followed = len(tokens) - index - length >= 2
        return greeted or followed
    return False


def _name_length(tokens: list[str], index: int) -> int:
    """How many words at ``index`` form the name: 1, 2 for a split name such as "Pei Bo", or 0."""
    token = tokens[index]
    if token in GREETINGS:
        return 0
    if is_name(token):
        return 1
    following = tokens[index + 1] if index + 1 < len(tokens) else ""
    if (
        following
        and len(token) <= _SPLIT_PART
        and len(following) <= _SPLIT_PART
        and is_name(token + following)
    ):
        return 2
    return 0


FAREWELLS = (
    "tschüss",
    "tschüs",
    "tschau",
    "ciao",
    "bye",
    "ade",
    "adieu",
    "gute nacht",
    "bis später",
    "bis bald",
    "bis morgen",
    "schlaf gut",
    "auf wiedersehen",
    "machs gut",
    "mach s gut",
    "servus",
)
SLEEP_WORDS = frozenset(
    {"stopp", "stop", "halt", "ruhe", "schluss", "aufhören", "schlafen", "still", "pause"}
)
_SLEEP_COMMAND_MAX_WORDS = 5
_FAREWELL_REPLY_SECONDS = 10.0


def is_farewell(text: str) -> bool:
    """Return whether a transcript says goodbye, for example "Okay, tschüss Pebbo"."""
    lowered = " ".join(_WORD.findall(text.lower()))
    return any(re.search(rf"\b{re.escape(farewell)}\b", lowered) for farewell in FAREWELLS)


def is_sleep_command(text: str) -> bool:
    """Return whether a short transcript tells Pebbo to stop, for example "Halt, stopp bitte"."""
    tokens = _WORD.findall(text.lower())
    return 0 < len(tokens) <= _SLEEP_COMMAND_MAX_WORDS and any(token in SLEEP_WORDS for token in tokens)


def is_fragment(text: str) -> bool:
    """Return whether a transcript is only a short start of an utterance, such as "Hey"."""
    return len(_WORD.findall(text.lower())) <= 3


class PebboWakeStrategy(WakePhraseUserTurnStartStrategy):
    """Pipecat's wake phrase strategy with phonetic matching of Pebbo's name.

    A short pause after "Hey Pebbo," splits speech into two transcripts. A short fragment is
    therefore kept for a few seconds and checked together with the next transcript.

    While awake, "Stopp" or "Ruhe" ends the conversation at once without an answer, and a
    goodbye ends it after Pebbo has said goodbye.
    """

    def __init__(self, *, timeout: float, fragment_seconds: float = 4.0) -> None:
        super().__init__(phrases=["hey pebbo"], timeout=timeout)
        self._fragment = ""
        self._fragment_at = 0.0
        self._fragment_seconds = fragment_seconds
        # A goodbye is heard first, then Pebbo answers it, then the conversation ends.
        self._farewell: str | None = None  # None, "heard" or "replying"
        self._farewell_at = 0.0

    async def process_frame(self, frame: Frame) -> ProcessFrameResult | None:
        if self.state == _WakeState.AWAKE:
            if isinstance(frame, TranscriptionFrame) and is_sleep_command(frame.text):
                logger.info("Sleep command heard")
                await self.broadcast_frame(InterruptionFrame)
                await self.trigger_reset_aggregation()
                self.go_to_sleep()
                return None
            if isinstance(frame, TranscriptionFrame) and is_farewell(frame.text):
                self._farewell, self._farewell_at = "heard", time.monotonic()
            elif isinstance(frame, BotStartedSpeakingFrame) and self._farewell == "heard":
                self._farewell = "replying"
            elif isinstance(frame, BotStoppedSpeakingFrame) and self._farewell == "replying":
                self.go_to_sleep()
                return None
            elif self._farewell == "heard" and time.monotonic() - self._farewell_at > _FAREWELL_REPLY_SECONDS:
                self.go_to_sleep()  # No goodbye came, end the conversation anyway.
                return None
        return await super().process_frame(frame)

    @property
    def asleep(self) -> bool:
        return self.state != _WakeState.AWAKE

    def wake_up(self) -> None:
        """Wake Pebbo without the phrase, for example when a body's own wake word fired."""
        if self.state != _WakeState.AWAKE:
            self._fragment = ""
            self._transition_to_awake("hey pebbo")

    def go_to_sleep(self) -> None:
        """End the conversation until the next wake phrase."""
        self._farewell = None
        if self.state == _WakeState.AWAKE:
            self._transition_to_idle()

    def _check_wake_phrase(self, text: str) -> bool:
        now = time.monotonic()
        recent = self._fragment if now - self._fragment_at <= self._fragment_seconds else ""
        candidate = f"{recent} {text}".strip()
        if addresses_pebbo(candidate):
            self._fragment = ""
            logger.debug("Wake phrase detected")
            self._transition_to_awake("hey pebbo")
            return True
        self._fragment, self._fragment_at = (text, now) if is_fragment(text) else ("", 0.0)
        return False
