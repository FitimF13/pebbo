"""Turn a routine described in plain words into Pebbo's routine format.

The action agent sees every tool on every sentence, so its tool list must stay small. It
only passes the person's words to ``teach_routine``. This second, focused call to the
language model then fills in the trigger, conditions and actions, with the full routine
format and the tools a routine may use. Teaching a routine is rare, so the extra second
is spent only then.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from loguru import logger

from pebbo import clock


@dataclass(frozen=True)
class RoutineRequest:
    """What the person said, with what is needed to turn it into a routine."""

    text: str
    person: str
    # The routine Pebbo just read back, as JSON in the routine format, when the person changes it.
    draft: str = ""
    # Name and short description of each tool a routine action may use.
    tools: Sequence[tuple[str, str]] = ()


# Returns the arguments of ``teach_routine`` in the full format, or ``None``.
Structurer = Callable[[RoutineRequest, dict[str, Any]], Awaitable[dict[str, Any] | None]]
# The language model to use right now: base URL and model name.
Endpoint = Callable[[], tuple[str, str]]

PROMPT = "\n".join(
    [
        "Du wandelst eine Routine, die {person} Pebbo beibringen will, in genau einen Aufruf von "
        "teach_routine um. Pebbo ist ein kleiner Tischroboter bei einer Familie. Jetzt ist {now}, {weekday}.",
        "{draft}",
        "Werkzeuge, die eine Aktion vom Typ tool benutzen kann:",
        "{tools}",
        "Benutze nur diese Werkzeugnamen und ihre Argumente. Übernimm Uhrzeiten, Tage und Personen genau "
        "so, wie sie gesagt wurden. 'ich' ist {person}. Füge nichts hinzu, was nicht gesagt wurde: keine "
        "weiteren Aktionen, report nur true, wenn die Person eine Rückmeldung möchte. Rufe teach_routine "
        "immer auf, auch wenn etwas unklar ist.",
    ]
)


def prompt(request: RoutineRequest) -> str:
    moment = clock.now()
    draft = (
        f"Gerade offen ist dieser Entwurf: {request.draft} Will {request.person} ihn ändern, übernimm "
        f"alles unverändert und ändere nur, was gesagt wird. Beschreibt {request.person} eine andere "
        "Routine, baue nur die neue."
        if request.draft
        else ""
    )
    tools = "\n".join(f"- {name}: {description}" for name, description in request.tools) or "- (keine)"
    return PROMPT.format(
        person=request.person,
        now=moment.strftime("%Y-%m-%d %H:%M"),
        weekday=clock.WEEKDAYS[moment.weekday()],
        draft=draft,
        tools=tools,
    )


def llm_structurer(endpoint: Endpoint, timeout: float = 20.0) -> Structurer:
    """A structurer that asks the language model currently in use."""
    from pebbo.voice.actions import parse_tool_calls
    from pebbo.voice.ollama_setup import llm_request

    async def structure(request: RoutineRequest, schema: dict[str, Any]) -> dict[str, Any] | None:
        base_url, model = endpoint()
        body = {
            "model": model,
            "stream": False,
            "temperature": 0,
            "tools": [{"type": "function", "function": schema}],
            "messages": [
                {"role": "system", "content": prompt(request)},
                {"role": "user", "content": request.text},
            ],
        }
        # Small models now and then answer in words instead of calling the tool; one retry fixes that.
        for _attempt in range(2):
            try:
                raw = await asyncio.to_thread(llm_request, base_url, "/v1/chat/completions", body, timeout)
                calls = parse_tool_calls(json.loads(raw))
            except (OSError, ValueError) as error:
                logger.warning("Routine could not be structured: {}", type(error).__name__)
                return None
            for name, arguments in calls:
                if name == schema["name"]:
                    return arguments
            body["temperature"] = 0.4  # The same request would give the same answer again.
        return None

    return structure
