"""Clean model output before it is spoken.

Models sometimes add emojis, markdown or stage directions such as "*flattert mit den
Flügeln*". Those must not be read aloud. Emphasis such as "*super*" keeps its word.
"""

from __future__ import annotations

import re

_EMOJI = re.compile(
    "["
    "\U0001f000-\U0001faff"  # pictographs, emoticons, symbols
    "\U00002600-\U000027bf"  # misc symbols and dingbats
    "\U0001f1e6-\U0001f1ff"  # flags
    "‍️⃣"  # joiners and variation selectors
    "]+"
)
# A whole sentence-like action in asterisks: at the start, after sentence punctuation, or at the end.
_ACTION = re.compile(r"(^|(?<=[.!?…]))\s*\*[^*\n]{2,60}\*\s*(?=$|[A-ZÄÖÜ\s])")
_EMPHASIS = re.compile(r"\*{1,2}([^*\n]+)\*{1,2}")
# Emotion tags the model sometimes writes in the middle of a reply, such as "[neutral]".
_TAG = re.compile(r"\[\s*[a-zA-Z]{2,15}\s*\]")
_BRACKETED = re.compile(r"\((?:lacht|kichert|grinst|seufzt|zwinkert|lächelt)[^)]*\)", re.IGNORECASE)
_MARKUP = re.compile(r"[#_`~>|]")
_DASH = re.compile(r"\s*[–—]\s*")
_SPACES = re.compile(r"\s{2,}")


def clean_for_speech(text: str) -> str:
    """Remove emojis, stage directions and markdown, keeping emphasised words."""
    text = _EMOJI.sub("", text)
    text = _TAG.sub("", text)
    text = _ACTION.sub(" ", text)
    text = _BRACKETED.sub("", text)
    text = _EMPHASIS.sub(r"\1", text)
    text = _MARKUP.sub("", _DASH.sub(", ", text))
    return _SPACES.sub(" ", text).strip()


async def speech_transform(text: str, _text_type: object) -> str:
    """Pipecat text transform that cleans text right before speech synthesis."""
    return clean_for_speech(text)
