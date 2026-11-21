"""After a conversation: a short summary of what was talked about."""

from __future__ import annotations

import json
import re
from typing import Any

from pebbo.voice.ollama_setup import llm_request

# Older prompts let the model answer this instead of a summary. Given the choice, Ministral
# chose it even for "Ich gehe heute Abend mit Leon ins Kino", so the code decides instead.
EMPTY = "LEER"
PROMPT = (
    "Fasse in höchstens zwei kurzen Sätzen auf Deutsch zusammen, was {name} Pebbo erzählt hat oder worum "
    "{name} gebeten hat: Pläne, Vorlieben, Erlebnisse, Erinnerungen, offene Fragen. Schreib in der dritten "
    "Person und nenne {name} beim Namen. Erfinde nichts und bewerte nichts. Schreib nur die Sätze, ohne "
    "Überschrift und ohne Liste."
)
# Words that make a conversation small talk only, not worth a summary.
_SMALL_TALK = frozenset(
    [
        "hey",
        "hallo",
        "hi",
        "hoi",
        "pebbo",
        "pebo",
        "danke",
        "merci",
        "tschüss",
        "tschüs",
        "ciao",
        "bye",
        "gute",
        "nacht",
        "ja",
        "nein",
        "ok",
        "okay",
        "mhm",
        "genau",
        "gut",
        "super",
        "cool",
        "bis",
        "bald",
        "später",
        "morgen",
        "wie",
        "geht",
        "s",
        "es",
        "dir",
        "heute",
        "und",
        "selbst",
        "auch",
        "mir",
    ]
)
_MIN_CONTENT_WORDS = 4
_WORD = re.compile(r"[\wäöüß]+", re.IGNORECASE)
# The model sometimes appends the empty marker to a real summary ("Sara plant ... LEER").
_EMPTY_MARKER = re.compile(rf"\b{EMPTY}\b\W*", re.IGNORECASE)
_SENTENCE = re.compile(r"[^.!?]+[.!?]+")
_MAX_SENTENCES = 2


def transcript(messages: list[dict[str, Any]], name: str) -> str:
    lines = []
    for message in messages:
        role, content = message.get("role"), message.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            lines.append(f"{name if role == 'user' else 'Pebbo'}: {content.strip()}")
    return "\n".join(lines)


def user_turns(messages: list[dict[str, Any]]) -> int:
    return sum(1 for message in messages if message.get("role") == "user")


def worth_summarising(messages: list[dict[str, Any]]) -> bool:
    """Whether the person said more than greetings, thanks and goodbyes."""
    words = [
        word
        for message in messages
        if message.get("role") == "user" and isinstance(message.get("content"), str)
        for word in _WORD.findall(message["content"].lower())
    ]
    return sum(word not in _SMALL_TALK for word in words) >= _MIN_CONTENT_WORDS


def parse_summary(reply: str) -> str | None:
    """The summary in the model's reply, or ``None`` if it found nothing worth keeping."""
    text = _EMPTY_MARKER.sub("", reply.replace("*", "")).strip()
    # Only the first paragraph, before any list, and at most two sentences.
    paragraph = re.split(r"\n|\s-\s", text, maxsplit=1)[0].strip()
    sentences = [sentence.strip() for sentence in _SENTENCE.findall(paragraph)]
    summary = " ".join(sentences[:_MAX_SENTENCES]) or paragraph
    return summary or None


def summarize(base_url: str, model: str, messages: list[dict[str, Any]], name: str) -> str | None:
    """Summarise a conversation with the local model. Returns ``None`` if nothing worth keeping was said."""
    text = transcript(messages, name)
    if not text or not worth_summarising(messages):
        return None
    body = {
        "model": model,
        "stream": False,
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": PROMPT.format(name=name)},
            {"role": "user", "content": text},
        ],
    }
    reply = json.loads(llm_request(base_url, "/api/chat", body, timeout=60))
    return parse_summary(str(reply.get("message", {}).get("content", "")))
