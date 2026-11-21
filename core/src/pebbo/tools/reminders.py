"""Tools for reminders that Pebbo says out loud when they are due."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from pebbo import clock
from pebbo.tools.memory import overlap, similarity
from pebbo.tools.registry import Tool, ToolContext, ToolRegistry, ToolResult, speaker, text_argument

# How alike two reminder tasks must be to count as the same (0 to 1).
SAME_TASK = 0.75
# Two reminders for the same task closer than this are the same reminder said twice.
SAME_REMINDER_SECONDS = 10 * 60
_LEAD = re.compile(
    r"^\s*(?:(?:bitte\s+)?erinnere?\s+(?:mich|dich|[A-ZÄÖÜ][\wäöüß-]*)\s+(?:bitte\s+)?(?:daran,?\s*|an\s+|ans\s+)?"
    r"|denk\s+dran:?\s*|nicht\s+vergessen:?\s*)",
    re.IGNORECASE,
)


def reminder_task(text: str) -> str:
    """Keep only the task of a reminder, for example "Training" from "Erinnere mich ans Training"."""
    task = _LEAD.sub("", text.replace("ß", "ss")).strip().rstrip("!.")
    return task[:1].upper() + task[1:] if task else text.strip()


def spoken(timestamp: float) -> str:
    return clock.spoken_datetime(datetime.fromtimestamp(timestamp, clock.timezone()))


def due_moment(arguments: dict[str, Any]) -> datetime:
    """When a reminder is due: in a number of minutes from now, or at a local date and time.

    Relative times are short for the model to write and leave no room for arithmetic errors.
    """
    minutes = arguments.get("in_minutes")
    if minutes not in (None, ""):
        try:
            value = float(minutes)
        except (TypeError, ValueError) as error:
            raise ValueError("Die Anzahl Minuten ist keine Zahl.") from error
        if not 0 < value <= 366 * 24 * 60:
            raise ValueError("Erinnerungen gehen höchstens ein Jahr im Voraus.")
        return clock.now() + timedelta(minutes=value)
    return clock.parse_due(text_argument(arguments, "due"))


async def set_reminder(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    person = speaker(context)
    try:
        moment = due_moment(arguments)
    except ValueError as error:
        return ToolResult(f"Die Erinnerung konnte ich nicht planen. {error}", ok=False, outcome="invalid")
    task = reminder_task(text_argument(arguments, "text"))
    if not task:
        return ToolResult(ok=False, outcome="empty")
    store = context.store
    same = next(
        (
            r
            for r in store.reminders(person.id)
            if abs(r.due_at - moment.timestamp()) <= SAME_REMINDER_SECONDS
            and similarity(r.text, task) >= SAME_TASK
        ),
        None,
    )
    if same is not None:
        return ToolResult(f"Die Erinnerung habe ich schon: {spoken(same.due_at)}.", outcome="known")
    store.add_reminder(person.id, task, moment.timestamp())
    return ToolResult(
        f"Ich erinnere dich {clock.spoken_datetime(moment)}: {task}.",
        outcome="planned",
        data={"text": task, "due": moment.isoformat()},
    )


async def cancel_reminder(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    person = speaker(context)
    what = text_argument(arguments, "what")
    reminders = context.store.reminders(person.id)
    best = max(reminders, key=lambda r: (overlap(r.text, what), similarity(r.text, what)), default=None)
    if best is None or (overlap(best.text, what) == 0 and len(reminders) > 1):
        return ToolResult("Diese Erinnerung habe ich nicht gefunden.", ok=False, outcome="missing")
    context.store.cancel_reminder(best.id)
    return ToolResult(f"Erinnerung gelöscht: {best.text}.", outcome="deleted", data={"text": best.text})


def register_reminder_tools(registry: ToolRegistry) -> None:
    registry.register(
        Tool(
            name="set_reminder",
            description=(
                "Plant eine Erinnerung, die Pebbo zur Zeit laut ansagt. Nur wenn die Person selbst "
                "erinnert werden möchte oder ein Angebot von Pebbo dazu annimmt, nie für Fragen. Ungenaue "
                "Zeiten: 'morgen früh' ist 07:30, 'mittags' 12:00, 'heute Abend' 19:00."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Nur die Sache, z. B. 'Tee' oder 'Paket mitnehmen'",
                    },
                    "in_minutes": {
                        "type": "number",
                        "description": "Für 'in X Minuten/Stunden': Minuten ab jetzt. Sonst weglassen.",
                    },
                    "due": {
                        "type": "string",
                        "description": "Für eine Uhrzeit oder einen Tag: lokal im Format JJJJ-MM-TTTHH:MM",
                    },
                },
                "required": ["text"],
            },
            run=set_reminder,
        )
    )
    registry.register(
        Tool(
            name="cancel_reminder",
            description="Sagt eine offene Erinnerung der Person ab, wenn sie das möchte.",
            parameters={
                "type": "object",
                "properties": {"what": {"type": "string", "description": "Woran sie erinnern sollte"}},
                "required": ["what"],
            },
            run=cancel_reminder,
        )
    )
