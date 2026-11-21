"""After a conversation: a short summary of what was talked about."""

from __future__ import annotations

import json
from typing import Any

from pebbo.voice.ollama_setup import llm_request

EMPTY = "LEER"
PROMPT = (
    "Fasse das Gespräch zwischen {name} und Pebbo in höchstens zwei kurzen Sätzen auf Deutsch zusammen. "
    "Nenne nur, was später nützlich sein kann: Pläne, Vorlieben, Erlebnisse, offene Fragen. Schreib in der "
    "dritten Person und nenne {name} beim Namen statt 'er' oder 'sie'. Erfinde nichts. Wenn nichts "
    "davon besprochen wurde, antworte nur mit {empty}."
)


def transcript(messages: list[dict[str, Any]], name: str) -> str:
    lines = []
    for message in messages:
        role, content = message.get("role"), message.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            lines.append(f"{name if role == 'user' else 'Pebbo'}: {content.strip()}")
    return "\n".join(lines)


def user_turns(messages: list[dict[str, Any]]) -> int:
    return sum(1 for message in messages if message.get("role") == "user")


def summarize(base_url: str, model: str, messages: list[dict[str, Any]], name: str) -> str | None:
    """Summarise a conversation with the local model. Returns ``None`` if nothing worth keeping was said."""
    text = transcript(messages, name)
    if not text:
        return None
    body = {
        "model": model,
        "stream": False,
        "options": {"temperature": 0.2},
        "messages": [
            {"role": "system", "content": PROMPT.format(name=name, empty=EMPTY)},
            {"role": "user", "content": text},
        ],
    }
    reply = json.loads(llm_request(base_url, "/api/chat", body, timeout=60))
    summary = str(reply.get("message", {}).get("content", "")).replace("*", "").strip()
    if not summary or EMPTY in summary.upper():
        return None
    return summary
