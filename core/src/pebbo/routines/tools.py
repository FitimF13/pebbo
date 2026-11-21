"""Tools that let people teach, confirm, pause, test and remove routines by talking.

The action agent passes a sentence such as "Wenn ich gehe und niemand mehr da ist, sag
tschüss" to ``teach_routine``, and a focused second call (``pebbo.routines.structure``)
turns it into a trigger, conditions and actions. That only creates a draft: Pebbo reads it
back in its own words and asks. The routine is saved active only after the person's yes
(``confirm_routine``). Routines that affect other people, watch someone else or use tools
only the owner may use also need the owner's approval.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pebbo import clock
from pebbo.routines.engine import Firing, RoutineEngine
from pebbo.routines.model import (
    ACTION_TYPES,
    CONDITION_TYPES,
    TRIGGER_TYPES,
    RoutineError,
    describe,
    limits,
    normalise,
    people_referenced,
)
from pebbo.routines.storage import Routine, RoutineBook, routine_book
from pebbo.routines.structure import RoutineRequest, Structurer
from pebbo.store import Person, Store
from pebbo.tools.memory import overlap, similarity
from pebbo.tools.registry import Tool, ToolContext, ToolRegistry, ToolResult, speaker, text_argument

NEEDS_OWNER = "Weil sie andere betrifft, muss sie danach der Besitzer im Kontrollzentrum freigeben."
NOT_FOUND = "Diese Routine habe ich nicht gefunden."
NOT_UNDERSTOOD = "Diese Routine habe ich nicht ganz verstanden. Sag sie mir bitte noch einmal anders."
ROUTINE_TOOLS = frozenset(
    {"teach_routine", "confirm_routine", "discard_routine", "list_routines", "pause_routine", "test_routine"}
)


def routine_text(routine: Routine, store: Store, person: Person | None) -> str:
    """A routine read back in German, addressed to ``person``."""
    return describe(routine.trigger, routine.conditions, routine.actions, routine.report, store, person)


def visible(book: RoutineBook, person: Person) -> list[Routine]:
    """The routines a person may see and manage: their own, the owner all of them."""
    return book.routines() if person.role == "owner" else book.routines(person.id)


def find(book: RoutineBook, person: Person, name: str, *, drafts_first: bool = False) -> Routine | None:
    """The routine a person means, by name or words from it. Without a name the newest draft."""
    candidates = visible(book, person)
    if not name:
        drafts = book.drafts(person.id)
        if drafts_first and drafts:
            return drafts[0]
        own = [r for r in candidates if r.person_id == person.id]
        return own[-1] if own and (len(own) == 1 or drafts_first) else None

    def score(routine: Routine) -> tuple[int, float]:
        return overlap(f"{routine.name} {routine.text}", name), similarity(routine.name, name)

    best = max(candidates, key=score, default=None)
    if best is None or (score(best)[0] == 0 and score(best)[1] < 0.6):
        return None
    return best


def conflicts(book: RoutineBook, trigger: dict[str, Any], exclude: int | None = None) -> list[Routine]:
    """Active routines that start on the same trigger, so the person can decide which wins."""
    return [r for r in book.routines(status="active") if r.trigger == trigger and r.id != exclude]


def _needs_owner(
    registry: ToolRegistry,
    person: Person,
    trigger: dict[str, Any],
    conditions: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    affects_others: bool,
) -> bool:
    owner_tools = any(
        a["type"] == "tool" and (tool := registry.get(a["tool"])) is not None and tool.permission == "owner"
        for a in actions
    )
    others = bool(people_referenced(trigger, conditions) - {person.id})
    return affects_others or owner_tools or others


def _short(description: str) -> str:
    """The first sentence of a tool description, for the list of tools a routine may use."""
    first = description.split(". ", 1)[0].split(": ", 1)[0].strip()
    return first if len(first) <= 120 else first[:117] + "..."


def _arguments(parameters: dict[str, Any]) -> str:
    """The argument names of a tool, so a routine action can fill them in."""
    names = [str(name) for name in (parameters.get("properties") or {}) if name != "explicit"]
    return f" (Argumente: {', '.join(names)})" if names else ""


def register_routine_tools(registry: ToolRegistry, structure: Structurer | None = None) -> None:
    """Add the routine tools. They check tool actions against this registry.

    ``structure`` turns the person's words into the routine format. Without it, ``teach_routine``
    needs the trigger, conditions and actions in its arguments, as in tests.
    """

    def tool_exists(name: str) -> bool:
        return registry.get(name) is not None

    async def structured(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any] | None:
        if arguments.get("trigger") or structure is None:
            return arguments
        person = speaker(context)
        text = text_argument(arguments, "text")
        if not text:
            return None
        drafts = routine_book(context.store).drafts(person.id)
        draft = ""
        if drafts:
            last = drafts[-1]
            fields = {
                "name": last.name,
                "trigger": last.trigger,
                "conditions": last.conditions,
                "actions": last.actions,
                "report": last.report,
            }
            draft = json.dumps(fields, ensure_ascii=False)
        tools = [
            (tool.name, _short(tool.description) + _arguments(tool.parameters))
            for tool in registry.tools()
            if tool.name not in ROUTINE_TOOLS and registry.denial(tool, context) is None
        ]
        request = RoutineRequest(text, person.name, draft, tools)
        filled = await structure(request, TEACH_SCHEMA)
        if filled is None:
            return None
        return {**filled, "text": text}

    async def teach(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        person = speaker(context)
        store = context.store
        filled = await structured(context, arguments)
        if filled is None:
            return ToolResult(NOT_UNDERSTOOD, ok=False, outcome="incomplete")
        arguments = filled
        try:
            trigger, conditions, actions = normalise(
                arguments.get("trigger"),
                arguments.get("conditions"),
                arguments.get("actions"),
                store,
                person,
                tool_exists,
            )
        except RoutineError as error:
            return ToolResult(f"{error}", ok=False, outcome="incomplete")
        book = routine_book(store)
        # A new version while the person is still deciding replaces the old draft.
        for draft in book.drafts(person.id):
            book.delete(draft.id)
        cooldown, daily = limits(arguments.get("cooldown_minutes"), arguments.get("daily_limit"))
        needs_owner = _needs_owner(
            registry, person, trigger, conditions, actions, arguments.get("affects_others") is True
        )
        routine = book.add(
            person.id,
            text_argument(arguments, "name") or "Routine",
            text_argument(arguments, "text"),
            trigger,
            conditions,
            actions,
            report=arguments.get("report") is True,
            needs_owner=needs_owner,
            cooldown_minutes=cooldown,
            daily_limit=daily,
        )
        parts = [f"Ich habe verstanden: {routine_text(routine, store, person)}"]
        clashes = conflicts(book, trigger)
        if clashes:
            names = ", ".join(f"«{r.name}»" for r in clashes)
            parts.append(f"Achtung, {names} startet auch dann. Sag mir, ob beide gelten sollen.")
        if needs_owner and person.role != "owner":
            parts.append(NEEDS_OWNER)
        parts.append("Soll ich die Routine so speichern?")
        return ToolResult(" ".join(parts), outcome="draft", data={"routine_id": routine.id})

    async def confirm(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        person = speaker(context)
        book = routine_book(context.store)
        drafts = book.drafts(person.id)
        name = text_argument(arguments, "name")
        routine = find(book, person, name, drafts_first=True) if name else (drafts[0] if drafts else None)
        if routine is None or routine.status != "draft":
            return ToolResult(
                "Ich habe gerade keine neue Routine, die auf ein Ja wartet.", ok=False, outcome="missing"
            )
        if routine.needs_owner and person.role != "owner":
            book.confirm(routine.id)
            return ToolResult(
                f"Danke! «{routine.name}» gilt, sobald der Besitzer sie im Kontrollzentrum freigibt.",
                outcome="waiting",
            )
        book.activate(routine.id, approved_by=person.id if routine.needs_owner else None)
        return ToolResult(f"Gespeichert: «{routine.name}» gilt ab jetzt.", outcome="active")

    async def discard(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        person = speaker(context)
        book = routine_book(context.store)
        routine = find(book, person, text_argument(arguments, "name"), drafts_first=True)
        if routine is None:
            return ToolResult(NOT_FOUND, ok=False, outcome="missing")
        book.delete(routine.id)
        if routine.status == "draft" and routine.confirmed_at is None:
            return ToolResult("Okay, die Routine speichere ich nicht.", outcome="discarded")
        return ToolResult(f"Routine gelöscht: «{routine.name}».", outcome="deleted")

    async def list_all(context: ToolContext, _arguments: dict[str, Any]) -> ToolResult:
        person = speaker(context)
        book = routine_book(context.store)
        routines = [r for r in visible(book, person) if r.status != "draft" or r.confirmed_at is not None]
        if not routines:
            return ToolResult("Du hast noch keine Routinen.", outcome="empty")
        lines = []
        for routine in routines[:8]:
            state = {"active": "", "paused": " (pausiert)"}.get(routine.status, " (wartet auf Freigabe)")
            lines.append(f"«{routine.name}»{state}: {routine_text(routine, context.store, person)}")
        count = len(routines)
        head = "Du hast eine Routine." if count == 1 else f"Du hast {count} Routinen."
        return ToolResult(f"{head} " + " ".join(lines), outcome="listed", data={"count": count})

    async def pause(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        person = speaker(context)
        book = routine_book(context.store)
        routine = find(book, person, text_argument(arguments, "name"))
        if routine is None or routine.status == "draft":
            return ToolResult(NOT_FOUND, ok=False, outcome="missing")
        if arguments.get("resume") is True:
            book.set_status(routine.id, "active")
            return ToolResult(f"«{routine.name}» läuft wieder.", outcome="active")
        book.set_status(routine.id, "paused")
        return ToolResult(f"«{routine.name}» ist pausiert.", outcome="paused")

    async def test(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        person = speaker(context)
        store = context.store
        book = routine_book(store)
        routine = find(book, person, text_argument(arguments, "name"), drafts_first=True)
        if routine is None:
            return ToolResult(NOT_FOUND, ok=False, outcome="missing")
        return ToolResult(await dry_run(RoutineEngine(store, registry), routine), outcome="tested")

    registry.register(
        Tool(
            name="teach_routine",
            description=(
                "Bringt Pebbo eine neue Routine bei: wenn die Person möchte, dass Pebbo künftig von selbst "
                "etwas tut, sobald etwas eintritt, z. B. 'Wenn ich gehe und niemand mehr da ist, schalte "
                "die Lichter aus' oder 'Jeden Werktag um sieben sag mir guten Morgen'. Auch wenn sie eine "
                "Routine, die Pebbo gerade vorgelesen hat, noch ändern möchte. Nicht für eine einmalige "
                "Erinnerung (dafür set_reminder). Pebbo liest die Routine vor und fragt, bevor sie gilt."
            ),
            parameters=TEACH_SHORT if structure is not None else TEACH_PARAMETERS,
            run=teach,
        )
    )
    registry.register(
        Tool(
            name="confirm_routine",
            description=(
                "Speichert die Routine, die Pebbo gerade vorgelesen hat, wenn die Person auf die Frage "
                "'Soll ich die Routine so speichern?' zustimmt (ja, passt, genau so)."
            ),
            parameters=_NAME_ONLY,
            run=confirm,
        )
    )
    registry.register(
        Tool(
            name="discard_routine",
            description=(
                "Verwirft die gerade vorgelesene Routine, wenn die Person sie doch nicht möchte, oder löscht "
                "eine gespeicherte Routine, wenn die Person das möchte."
            ),
            parameters=_NAME_ONLY,
            run=discard,
        )
    )
    registry.register(
        Tool(
            name="list_routines",
            description="Zählt die Routinen der Person auf, wenn sie wissen möchte, welche Routinen es gibt.",
            parameters={"type": "object", "properties": {}},
            run=list_all,
        )
    )
    registry.register(
        Tool(
            name="pause_routine",
            description=(
                "Pausiert eine Routine, wenn die Person sie vorübergehend nicht möchte, oder setzt sie mit "
                "resume=true wieder fort."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name oder Inhalt der Routine"},
                    "resume": {"type": "boolean", "description": "true zum Fortsetzen, sonst false"},
                },
                "required": ["name"],
            },
            run=pause,
        )
    )
    registry.register(
        Tool(
            name="test_routine",
            description=(
                "Probelauf einer Routine, wenn die Person 'probier es jetzt' oder 'teste die Routine' sagt: "
                "Pebbo prüft die Bedingungen und sagt, was er tun würde, ohne es zu tun."
            ),
            parameters=_NAME_ONLY,
            run=test,
        )
    )


async def dry_run(engine: RoutineEngine, routine: Routine, moment: datetime | None = None) -> str:
    """Check a routine now and say what it would do, without doing it. The run is logged."""
    run = await engine.run(routine, Firing("Probelauf"), moment or clock.now(), dry_run=True)
    failed = [c["text"] for c in run.conditions if not c["ok"]]
    doing = [a["text"] for a in run.actions]
    if failed:
        return (
            f"Gerade würde «{routine.name}» nichts tun, weil nicht erfüllt ist, dass {' und '.join(failed)}. "
            f"Sonst {_would(doing)}."
        )
    return f"Wenn «{routine.name}» jetzt liefe, {_would(doing)}."


def _would(doing: list[str]) -> str:
    """ "sage ich «Hallo»" and "nutze ich «x»" as "würde ich «Hallo» sagen und «x» nutzen"."""
    phrases = []
    for text in doing:
        verb, _, rest = text.partition(" ich ")
        infinitive = {"sage": "sagen", "erinnere": "erinnern", "nutze": "nutzen"}.get(verb, verb)
        phrases.append(f"{rest} {infinitive}")
    joined = phrases[0] if len(phrases) == 1 else ", ".join(phrases[:-1]) + " und " + phrases[-1]
    return f"würde ich {joined}"


_NAME_ONLY: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "Name oder Inhalt der Routine, leer für die gerade besprochene",
        }
    },
}

TEACH_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Kurzer Name, z. B. 'Lichter aus beim Gehen'"},
        "text": {"type": "string", "description": "Was die Person gesagt hat"},
        "trigger": {
            "type": "object",
            "description": "Wann die Routine startet",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": list(TRIGGER_TYPES),
                    "description": (
                        "time: zu einer Uhrzeit; sunrise oder sunset: bei Sonnenaufgang oder -untergang; "
                        "arrive oder leave: wenn jemand heimkommt oder geht; device: wenn ein Gerät seinen "
                        "Zustand ändert"
                    ),
                },
                "at": {"type": "string", "description": "Bei time: Uhrzeit HH:MM"},
                "weekdays": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Wochentage wie Mo, Di, Mi, Do, Fr, Sa, So oder werktags; leer heisst täglich"
                    ),
                },
                "offset_minutes": {
                    "type": "integer",
                    "description": "Bei sunrise oder sunset: Minuten danach (positiv) oder davor (negativ)",
                },
                "who": {
                    "type": "string",
                    "description": (
                        "Bei arrive oder leave: ein Vorname, 'ich' für die sprechende Person, 'jemand', "
                        "'erste' (die erste Person kommt) oder 'letzte' (die letzte Person geht)"
                    ),
                },
                "entity": {"type": "string", "description": "Bei device: das Gerät"},
                "to": {"type": "string", "description": "Bei device: der neue Zustand, z. B. on oder off"},
            },
            "required": ["type"],
        },
        "conditions": {
            "type": "array",
            "description": "Nur wenn ... (leer, wenn es keine Bedingung gibt)",
            "items": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": list(CONDITION_TYPES),
                        "description": (
                            "weekday: an bestimmten Tagen; time_window: zwischen zwei Uhrzeiten; "
                            "quiet_hours oder outside_quiet_hours: während oder ausserhalb der Ruhezeit; "
                            "person_home oder "
                            "person_away: eine Person ist da oder weg; nobody_home: niemand ist da; "
                            "someone_home: jemand ist da; device_state: ein Gerät hat einen Zustand"
                        ),
                    },
                    "days": {"type": "array", "items": {"type": "string"}, "description": "Bei weekday"},
                    "from": {"type": "string", "description": "Bei time_window: HH:MM"},
                    "to": {"type": "string", "description": "Bei time_window: HH:MM"},
                    "who": {
                        "type": "string",
                        "description": "Bei person_home oder person_away: Vorname oder 'ich'",
                    },
                    "entity": {"type": "string", "description": "Bei device_state: das Gerät"},
                    "state": {"type": "string", "description": "Bei device_state: der Zustand"},
                },
                "required": ["type"],
            },
        },
        "actions": {
            "type": "array",
            "description": "Was Pebbo dann tut, der Reihe nach",
            "items": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": list(ACTION_TYPES),
                        "description": (
                            "say: etwas laut sagen; remind: die Person an etwas erinnern; tool: ein anderes "
                            "Werkzeug von Pebbo benutzen, z. B. für Geräte"
                        ),
                    },
                    "text": {"type": "string", "description": "Bei say und remind: der Text"},
                    "in_minutes": {"type": "integer", "description": "Bei remind: wie viele Minuten später"},
                    "tool": {"type": "string", "description": "Bei tool: der Name des Werkzeugs"},
                    "arguments": {"type": "object", "description": "Bei tool: die Argumente des Werkzeugs"},
                    "spoken": {
                        "type": "string",
                        "description": (
                            "Nur bei tool: was dann passiert, kurz auf Deutsch, z. B. 'Lichter ausschalten'"
                        ),
                    },
                },
                "required": ["type"],
            },
        },
        "report": {
            "type": "boolean",
            "description": "true, wenn Pebbo danach sagen soll, was er getan hat",
        },
        "affects_others": {
            "type": "boolean",
            "description": (
                "true, wenn die Routine andere Personen betrifft oder Türen, Schlösser oder Alarme steuert"
            ),
        },
        "cooldown_minutes": {
            "type": "integer",
            "description": "Mindestabstand zwischen zwei Läufen, sonst leer",
        },
        "daily_limit": {"type": "integer", "description": "Höchstens so oft pro Tag, sonst leer"},
    },
    "required": ["name", "trigger", "actions"],
}

# What the action agent sees: only the person's words. The full format goes to the structurer.
TEACH_SHORT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "text": {
            "type": "string",
            "description": (
                "Die Routine in den Worten der Person, vollständig. Bei einer Änderung: die Änderung."
            ),
        }
    },
    "required": ["text"],
}

TEACH_SCHEMA: dict[str, Any] = {
    "name": "teach_routine",
    "description": (
        "Legt eine Routine an: wann sie startet, unter welchen Bedingungen und was Pebbo dann tut."
    ),
    "parameters": TEACH_PARAMETERS,
}
