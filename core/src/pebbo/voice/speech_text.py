"""Clean model output before it is spoken.

Models sometimes add emojis, markdown or stage directions such as "*flattert mit den
Flügeln*". Those must not be read aloud. Emphasis such as "*super*" keeps its word.

Stage notes can also span sentences, such as "(Nach der Antwort: *Erinnerung aktiviert:
"Sara, du wolltest über Tee reden. Frag Pebbo!")*". Speech is synthesised one sentence at a
time, so :class:`StageNoteFilter` removes them from the streamed answer before it is split
into sentences: anything in parentheses or square brackets, text in asterisks that is longer
than a short emphasis, and short actions in asterisks such as "*zwinkert*" at the start or
end of a sentence.

Pocket TTS does not find the end of a sentence that contains typographic apostrophes or
quotation marks ("geht’s", „super“). It then speaks for seconds until its length limit, so
they are replaced by plain apostrophes or left out.
"""

from __future__ import annotations

import re

from pipecat.frames.frames import Frame, InterruptionFrame, LLMFullResponseStartFrame, LLMTextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

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
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "´": "'", "`": "'"})
_QUOTES = re.compile('[„“”‟«»‹›"]')
_NOTE = re.compile(r"\*+[^*]+\*+[.!?]?|\*?\([^()]+\)\*?[.!?]?")
_SPACES = re.compile(r"\s{2,}")


# Text in asterisks with more words than this, or with punctuation, is a note, not emphasis.
_MAX_EMPHASIS_WORDS = 3
_NOTE_PUNCTUATION = re.compile(r"[:.!?;()\[\]\"„“”«»]")
_OPENING, _CLOSING = "([", ")]"
_SENTENCE_END = ".!?…:"


class StageNotes:
    """Removes stage notes from an answer that arrives in pieces.

    Text in parentheses or square brackets is never spoken. Text in asterisks is held back
    until its closing asterisk. A few words in the middle of a sentence are emphasis and keep
    their words without the asterisks ("ein *guter* Plan"). At the start or end of a sentence
    they are an action such as "*zwinkert*", and anything longer is a note: both are dropped.
    An asterisk that is never closed starts a note.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Start a new answer."""
        self._depth = 0  # how many parentheses or brackets are open
        self._starred: str | None = None  # the text since an opening asterisk
        self._stars = 0  # how many asterisks opened it, 2 for "**bold**"
        self._skip_stars = 0  # the rest of a closing "**"
        self._after_note = False  # right after a closing parenthesis or bracket
        self._last = ""  # the last character let through that is not a space

    def feed(self, text: str) -> str:
        """The part of ``text`` that may be spoken, as far as it can be decided yet."""
        out: list[str] = []
        for char in text:
            after_note, self._after_note = self._after_note, False
            if char == "*" and (self._skip_stars or (after_note and self._starred is None)):
                # The rest of a closing "**", or a stray asterisk around a note: "(…)*".
                self._skip_stars = max(0, self._skip_stars - 1)
                self._after_note = after_note
                continue
            self._skip_stars = 0
            if self._starred is not None:
                out.append(self._in_asterisks(char))
            elif char in _OPENING:
                self._depth += 1
            elif char in _CLOSING:
                self._depth = max(0, self._depth - 1)
                self._after_note = True
            elif self._depth:
                continue
            elif char == "*":
                self._starred, self._stars = "", 1
            else:
                out.append(char)
                self._last = char if not char.isspace() else self._last
        return "".join(out)

    def flush(self) -> str:
        """The end of the answer: an unclosed note is dropped."""
        self.reset()
        return ""

    def _in_asterisks(self, char: str) -> str:
        """Collect text in asterisks. Returns its words once closed, if it is emphasis."""
        starred = self._starred or ""
        if char != "*":
            self._starred = starred + char
            return ""
        if not starred:
            self._stars += 1
            return ""
        self._starred, self._skip_stars = None, self._stars - 1
        within_sentence = bool(self._last) and self._last not in _SENTENCE_END
        if (
            not within_sentence
            or len(starred.split()) > _MAX_EMPHASIS_WORDS
            or _NOTE_PUNCTUATION.search(starred)
        ):
            return ""
        self._last = starred.strip()[-1:] or self._last
        return starred


def strip_notes(text: str) -> str:
    """Remove stage notes from a whole answer, as :class:`StageNotes` does for a streamed one."""
    notes = StageNotes()
    return notes.feed(text) + notes.flush()


class StageNoteFilter(FrameProcessor):
    """Removes stage notes from the language model's streamed answer before it is spoken.

    Sits before speech synthesis. Text the system says itself (``TTSSpeakFrame``) passes
    unchanged.
    """

    def __init__(self) -> None:
        super().__init__()
        self._notes = StageNotes()

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, (LLMFullResponseStartFrame, InterruptionFrame)):
            self._notes.reset()
        elif isinstance(frame, LLMTextFrame) and direction == FrameDirection.DOWNSTREAM:
            frame.text = self._notes.feed(frame.text)
            if not frame.text:
                return
        await self.push_frame(frame, direction)


def clean_for_speech(text: str) -> str:
    """Remove emojis, stage directions and markdown, keeping emphasised words."""
    text = _QUOTES.sub("", strip_notes(text).translate(_APOSTROPHES))
    # A note the model opens with an asterisk and closes in a later sentence, such as
    # "*Erinnerung bestätigt: Du bist Sara.*", arrives here one sentence at a time.
    if text.lstrip().startswith("*") and text.count("*") % 2:
        return ""
    # A whole sentence in asterisks or parentheses is a note such as "*Das System merkt sich,
    # dass Sara Kaffee ohne Zucker trinkt.*", never something to say.
    if _NOTE.fullmatch(text.strip()):
        return ""
    text = _EMOJI.sub("", text)
    text = _TAG.sub("", text)
    text = _ACTION.sub(" ", text)
    text = _BRACKETED.sub("", text)
    text = _EMPHASIS.sub(r"\1", text)
    text = _MARKUP.sub("", _DASH.sub(", ", text)).replace("*", "")
    return _SPACES.sub(" ", text).strip()


async def speech_transform(text: str, _text_type: object) -> str:
    """Pipecat text transform that cleans text right before speech synthesis."""
    return clean_for_speech(text)
