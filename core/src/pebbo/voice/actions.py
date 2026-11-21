"""The action agent: after every sentence, decide which of Pebbo's tools to use.

Pebbo has no list of command words. After each sentence a separate, focused call to the
local model reads the end of the conversation, what Pebbo already knows and the descriptions
of all registered tools (see ``pebbo.tools``), and chooses the actions itself, like an
attentive person would. Small local models call tools reliably in such a short, focused
request, but rarely while chatting, so the conversation model itself has no tools. It runs
in the background while Pebbo answers.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from pebbo import clock
from pebbo.voice.ollama_setup import llm_request

# How many earlier lines the decision sees, for "das" or "ja, mach das". More lines confuse small models.
RECENT_LINES = 2
# The name the agent sees for a voice Pebbo does not know.
GUEST = "Gast"

DECISION_PROMPT = "\n".join(
    [
        "Du bist der Teil von Pebbo, der handelt. Pebbo ist ein kleiner Tischroboter, der bei einer Familie "
        "wohnt. Du liest das Ende eines Gesprächs zwischen einer Person und Pebbo und entscheidest wie ein "
        "aufmerksamer Mensch, ob Pebbo jetzt eines seiner Werkzeuge benutzen soll. Die Nachricht nennt die "
        "Zeit, wer spricht und was Pebbo schon weiss.",
        "",
        "So entscheidest du:",
        "- Es zählt nur die letzte Äusserung der Person. Die Zeilen davor sind Zusammenhang, zum Beispiel "
        'worauf sich "das" bezieht oder was Pebbo gerade angeboten hat.',
        "- Benutze ein Werkzeug, wenn die Person etwas möchte, das ein Werkzeug erledigt, oder wenn die "
        "Beschreibung eines Werkzeugs auf die Äusserung passt. Mehrere Werkzeuge sind erlaubt.",
        "- Fragen beantwortet Pebbo selbst aus dem, was oben steht, ausser die Beschreibung eines Werkzeugs "
        'nennt genau diese Frage. "Erinnerst du dich ...?", '
        '"Weisst du noch ...?" oder "Welche Erinnerungen habe ich?" brauchen kein Werkzeug.',
        "- Erfinde nichts. Übernimm Inhalte nur aus dem Gespräch.",
        "- Wenn nichts zu tun ist, rufe nothing auf.",
    ]
)

NOTHING: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "nothing",
        "description": "Nichts zu tun.",
        "parameters": {"type": "object", "properties": {}},
    },
}


def known_block(name: str, facts: Sequence[str], reminders: Sequence[str]) -> str:
    """What Pebbo already knows, so the decision can avoid duplicates and resolve corrections."""
    if name == GUEST:
        return "Die Stimme ist unbekannt, es spricht ein Gast. Für Gäste speichert Pebbo nichts."
    lines = [f"Was Pebbo schon über {name} weiss:"]
    lines += [f"- {fact}" for fact in facts] or ["- noch nichts"]
    if reminders:
        lines.append("Offene Erinnerungen:")
        lines += [f"- {reminder}" for reminder in reminders]
    return "\n".join(lines)


def recent_lines(messages: Sequence[dict[str, Any]], name: str) -> str:
    """The person's last sentence, with the two lines before it as context."""
    lines = []
    for message in messages:
        role, content = message.get("role"), message.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            lines.append((role, f"{name if role == 'user' else 'Pebbo'}: {content.strip()}"))
    if not lines or lines[-1][0] != "user":
        return "\n".join(line for _, line in lines[-RECENT_LINES:])
    before = [line for _, line in lines[-RECENT_LINES - 1 : -1]]
    last = lines[-1][1].split(": ", 1)[1]
    parts = ["Davor im Gespräch:", *before, ""] if before else []
    return "\n".join([*parts, f"Letzte Äusserung von {name}, nur darum geht es:", last])


def decision_message(
    messages: Sequence[dict[str, Any]],
    name: str,
    facts: Sequence[str] = (),
    reminders: Sequence[str] = (),
) -> str:
    """Everything that changes between turns: the time, who speaks, what Pebbo knows, the lines."""
    moment = clock.now()
    return "\n".join(
        [
            f"Jetzt ist {moment.isoformat(timespec='minutes')}, {clock.WEEKDAYS[moment.weekday()]}. "
            "Es spricht ein Gast mit unbekannter Stimme."
            if name == GUEST
            else f"Es spricht {name}.",
            "",
            known_block(name, facts, reminders),
            "",
            recent_lines(messages, name),
        ]
    )


def choose_actions(
    base_url: str,
    model: str,
    tools: Sequence[dict[str, Any]],
    messages: Sequence[dict[str, Any]],
    name: str,
    facts: Sequence[str] = (),
    reminders: Sequence[str] = (),
) -> list[tuple[str, dict[str, Any]]]:
    """Ask the model what to do after the person's last sentence. Returns ``(name, arguments)`` pairs."""
    body = {
        "model": model,
        "stream": False,
        "temperature": 0,
        "tools": [*tools, NOTHING],
        "messages": [
            # The system prompt and the tools stay the same from turn to turn, so Ollama reuses
            # them from its cache and only reads the short message (0.2 instead of 1.1 seconds).
            {"role": "system", "content": DECISION_PROMPT},
            {"role": "user", "content": decision_message(messages, name, facts, reminders)},
        ],
    }
    reply = json.loads(llm_request(base_url, "/v1/chat/completions", body, timeout=30))
    return parse_tool_calls(reply)


def parse_tool_calls(reply: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    message = reply.get("choices", [{}])[0].get("message", {})
    actions = []
    for call in message.get("tool_calls") or []:
        function = call.get("function", {})
        name = str(function.get("name", ""))
        try:
            arguments = json.loads(function.get("arguments") or "{}")
        except json.JSONDecodeError:
            continue
        if name and name != "nothing" and isinstance(arguments, dict):
            actions.append((name, arguments))
    return actions
