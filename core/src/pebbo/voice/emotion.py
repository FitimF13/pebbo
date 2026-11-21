"""Emotion tags in model replies.

The model starts every reply with a tag such as ``[happy]``. The tag drives Pebbo's face
and is removed before the text is spoken or stored.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from pipecat.frames.frames import Frame, LLMFullResponseEndFrame, LLMFullResponseStartFrame, LLMTextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

EMOTIONS = ("happy", "laughing", "surprised", "sad", "embarrassed", "sulky", "proud", "curious", "neutral")
# The model answers only with this tag when people are talking to each other, not to Pebbo.
IGNORE = "ignore"
_TAG = re.compile(r"^\s*\[\s*([a-zA-Z]+)\s*\]\s*")
_MAX_PREFIX = 24


def split_emotion(text: str) -> tuple[str | None, str]:
    """Split a leading emotion tag from text. Unknown tags are removed but not returned."""
    match = _TAG.match(text)
    if not match:
        return None, text
    emotion = match.group(1).lower()
    return (emotion if emotion in EMOTIONS or emotion == IGNORE else None), text[match.end() :]


class EmotionTagProcessor(FrameProcessor):
    """Removes the leading emotion tag from a streamed reply and reports the emotion.

    A reply tagged ``[ignore]`` is swallowed completely: the speech was not meant for Pebbo.
    """

    def __init__(self, on_emotion: Callable[[str], Awaitable[None]]) -> None:
        super().__init__()
        self._on_emotion = on_emotion
        self._buffer = ""
        self._deciding = False
        self._ignoring = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMFullResponseStartFrame):
            self._buffer, self._deciding, self._ignoring = "", True, False
            await self.push_frame(frame, direction)
        elif isinstance(frame, LLMTextFrame) and self._ignoring:
            return
        elif isinstance(frame, LLMTextFrame) and self._deciding:
            self._buffer += frame.text
            stripped = self._buffer.lstrip()
            if stripped.startswith("[") and "]" not in stripped and len(stripped) < _MAX_PREFIX:
                return  # Wait for the rest of the tag.
            await self._flush(direction)
        elif isinstance(frame, LLMFullResponseEndFrame):
            if self._deciding:
                await self._flush(direction)
            await self.push_frame(frame, direction)
        else:
            await self.push_frame(frame, direction)

    async def _flush(self, direction: FrameDirection) -> None:
        self._deciding = False
        emotion, rest = split_emotion(self._buffer)
        self._buffer = ""
        if emotion == IGNORE:
            self._ignoring = True
            await self._on_emotion(IGNORE)
            return
        if emotion:
            await self._on_emotion(emotion)
        if rest:
            await self.push_frame(LLMTextFrame(rest), direction)
