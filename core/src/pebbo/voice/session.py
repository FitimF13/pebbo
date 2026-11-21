"""State of one conversation: who is speaking and what was created in it."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import numpy as np
from loguru import logger

from pebbo.people.speaker import (
    LEARN_THRESHOLD,
    MATCH_THRESHOLD,
    OTHER_VOICE_THRESHOLD,
    SAMPLE_RATE,
    YOUNG_VOICEPRINT,
    Identification,
    SpeakerRecognizer,
    merged,
)
from pebbo.presence import presence_for
from pebbo.store import Person, Store

# An uncertain short turn does not turn a recognised person into a guest.
_SECONDS_TO_LOSE_IDENTITY = 3.0


@dataclass
class ConversationState:
    """Tracks the current speaker and the memories created during the conversation."""

    store: Store
    recognizer: SpeakerRecognizer | None
    person: Person | None = None
    score: float = 0.0
    # Running mean of the unknown voice, kept so that "Ich bin Sara" can be confirmed later.
    unknown_embedding: np.ndarray | None = None
    unknown_samples: int = 0
    created_memories: list[int] = field(default_factory=list)
    people_in_conversation: set[int] = field(default_factory=set)
    claimed_names: set[str] = field(default_factory=set)
    # A name heard before the voice was long enough to fingerprint, claimed on the next turn.
    pending_name: str | None = None
    # What the speaker said last, so tools can check what was really said.
    last_utterance: str = ""
    # The recognised person whose turns are in the language model's context. When someone else
    # speaks, those turns are removed so they never reach a guest or another person.
    history_owner: int | None = None
    _pending: asyncio.Task[None] | None = None

    @property
    def is_guest(self) -> bool:
        return self.person is None

    def history_person(self) -> Person | None:
        """The person the conversation in the context belongs to, ``None`` if only guests spoke."""
        return self.store.person(self.history_owner) if self.history_owner is not None else None

    def identify_in_background(self, samples: np.ndarray) -> None:
        """Identify the speaker of an utterance without blocking the audio pipeline."""
        if self.recognizer is None:
            return
        self._pending = asyncio.create_task(self._identify(samples))

    async def settled(self, timeout: float = 0.6) -> None:
        """Wait briefly for a running identification, so the answer uses the right person."""
        if self._pending and not self._pending.done():
            try:
                await asyncio.wait_for(asyncio.shield(self._pending), timeout)
            except TimeoutError:
                logger.debug("Speaker identification is still running")

    async def _identify(self, samples: np.ndarray) -> None:
        if self.recognizer is None:
            return
        seconds = len(samples) / SAMPLE_RATE
        result = await asyncio.to_thread(self.recognizer.identify, samples)
        if result is None:
            logger.info("Speaker: {:.1f} s of speech is too short to identify", seconds)
            return
        self.apply(result, seconds)
        who = f"person {self.person.id}" if self.person else "guest"
        logger.info("Speaker: {} (similarity {:.2f}, {:.1f} s)", who, result.score, seconds)

    def apply(self, result: Identification, seconds: float = _SECONDS_TO_LOSE_IDENTITY) -> None:
        """Update who is speaking. A short uncertain turn keeps the previous speaker."""
        if result.person_id is None:
            uncertain = result.score >= OTHER_VOICE_THRESHOLD
            if self.person is not None and uncertain and seconds < _SECONDS_TO_LOSE_IDENTITY:
                return
            self.person, self.score = None, result.score
            self.unknown_embedding, self.unknown_samples = merged(
                self.unknown_embedding, self.unknown_samples, result.embedding
            )
            return
        self.person, self.score = self.store.person(result.person_id), result.score
        self.unknown_embedding, self.unknown_samples = None, 0
        if self.person:
            self.people_in_conversation.add(self.person.id)
            presence_for(self.store).heard(self.person.id)
            # A new fingerprint from one short sentence is weak, so it also learns from
            # matching turns until it has a few samples.
            young = self.person.voice_samples < YOUNG_VOICEPRINT
            threshold = MATCH_THRESHOLD if young else LEARN_THRESHOLD
            if result.score >= threshold and self.recognizer is not None:
                self.recognizer.learn(self.person.id, result.embedding)

    def reset(self) -> None:
        """Start a fresh conversation. Who is speaking is decided again from the next utterance."""
        self.person, self.score = None, 0.0
        self.unknown_embedding, self.unknown_samples = None, 0
        self.created_memories.clear()
        self.people_in_conversation.clear()
        self.claimed_names.clear()
        self.pending_name = None
        self.last_utterance = ""
        self.history_owner = None
