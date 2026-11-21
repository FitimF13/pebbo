"""Tools for what Pebbo knows about people: remembering, forgetting and introductions."""

from __future__ import annotations

import itertools
import re
from difflib import SequenceMatcher
from typing import Any

from loguru import logger

from pebbo.store import Memory, Store
from pebbo.tools.registry import Tool, ToolContext, ToolRegistry, ToolResult, passive, speaker, text_argument

# How alike two facts must be to count as the same (0 to 1).
SAME_FACT = 0.92
# A stored fact this alike, starting with the same word, is the same topic and gets updated.
SAME_TOPIC = 0.8
_WORD = re.compile(r"[\wäöüß]+", re.IGNORECASE)
_MEMORY_SUBJECT = re.compile(
    r"^\s*(?:die person|der nutzer|die nutzerin|der benutzer|die benutzerin|der user|die userin)\s+",
    re.IGNORECASE,
)
_NAME = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)?")
_LAST = {"", "das", "zuletzt", "letzte", "das letzte", "das gerade", "eben"}
# How people introduce themselves. Without such words a name is about someone else.
_SELF_INTRODUCTION = re.compile(
    r"\b(?:ich\s+bin|ich\s+heisse|ich\s+heiße|mein\s+name\s+ist|hier\s+ist|hier\s+spricht|bin's|bins"
    r"|nenn\s+mich|i\s+am|i'm|my\s+name\s+is|this\s+is)\b",
    re.IGNORECASE,
)


def similarity(first: str, second: str) -> float:
    """How alike two short texts are, ignoring case and punctuation."""

    def words(text: str) -> str:
        return " ".join(_WORD.findall(text.lower()))

    return SequenceMatcher(None, words(first), words(second)).ratio()


def overlap(text: str, query: str) -> int:
    """How many words two texts share."""
    return len(set(_WORD.findall(text.lower())) & set(_WORD.findall(query.lower())))


def memory_text(text: str) -> str:
    """Store facts without a subject: "Mag Tee" instead of "Die Person mag Tee"."""
    # Pebbo writes Swiss Standard German, speech recognition sometimes writes "ß".
    fact = _MEMORY_SUBJECT.sub("", text.replace("ß", "ss")).strip().rstrip(".")
    return fact[:1].upper() + fact[1:] if fact else text.strip()


def known_facts(store: Store, person_id: int) -> list[str]:
    return [m.text for m in store.memories(person_id) if m.kind != "summary"]


def introduces_self(utterance: str, name: str) -> bool:
    """Whether a sentence introduces its speaker ("Ich bin Sara", "Sara hier"), not someone else."""
    if _SELF_INTRODUCTION.search(utterance):
        return True
    words = _WORD.findall(utterance.lower())
    return any(
        similarity(word, name) >= SAME_TOPIC and following == "hier"
        for word, following in itertools.pairwise(words)
    )


def clean_name(text: str) -> str:
    match = _NAME.search(text)
    if not match:
        return ""
    return "-".join(part[:1].upper() + part[1:].lower() for part in match.group(0).split("-"))


async def remember(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    person = speaker(context)
    fact = memory_text(text_argument(arguments, "text"))
    if not fact:
        return ToolResult(ok=False, outcome="empty")
    store = context.store
    known = next(
        (
            m
            for m in store.memories(person.id)
            if m.kind != "summary" and similarity(m.text, fact) >= SAME_FACT
        ),
        None,
    )
    quiet = passive(arguments)
    if known is not None:
        # Pebbo's answer already shows that it knows. Saying "I know" again sounds odd.
        return ToolResult(outcome="known")
    replaced = _replaced(store, person.id, text_argument(arguments, "replaces"), fact)
    if replaced is not None:
        store.delete_memory(replaced.id)
    memory = store.add_memory(person.id, "fact", fact, source="learned" if quiet else "said")
    if context.state is not None:
        context.state.created_memories.append(memory.id)
    if replaced is not None:
        return ToolResult(f"Alles klar, geändert: {fact}.", outcome="stored", data={"text": fact})
    return ToolResult(
        "" if quiet else f"Hab ich mir gemerkt: {memory.text}.", outcome="stored", data={"text": fact}
    )


def _replaced(store: Store, person_id: int, old: str, new: str) -> Memory | None:
    """The stored fact that a changed fact replaces.

    Either the agent names it, or the new fact is a variant of a stored one about the same
    thing ("Trinkt Kaffee mit Zucker" and "Trinkt Kaffee ohne Zucker"), which small models
    often do not mark as a change.
    """
    facts = [m for m in store.memories(person_id) if m.kind != "summary"]
    if old:
        named = max(facts, key=lambda m: similarity(m.text, old), default=None)
        if named is not None and similarity(named.text, old) >= 0.6 and overlap(named.text, new) > 0:
            return named
    first = _WORD.findall(new.lower())[:1]
    variants = [
        m
        for m in facts
        if similarity(m.text, new) >= SAME_TOPIC and _WORD.findall(m.text.lower())[:1] == first
    ]
    return max(variants, key=lambda m: similarity(m.text, new), default=None)


async def forget(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    person = speaker(context)
    what = text_argument(arguments, "what")
    store = context.store
    candidates = [m for m in store.memories(person.id) if m.kind != "summary"]
    created = context.state.created_memories if context.state is not None else []
    target = None
    if what.lower() in _LAST and created:
        target = next((m for m in candidates if m.id == created[-1]), None)
    if target is None and candidates:
        best = max(candidates, key=lambda m: (overlap(m.text, what), similarity(m.text, what)))
        target = best if overlap(best.text, what) > 0 else None
    if target is None:
        return ToolResult("Dazu hatte ich nichts gespeichert.", ok=False, outcome="missing")
    store.delete_memory(target.id)
    if target.id in created:
        created.remove(target.id)
    return ToolResult(f"Okay, vergessen: {target.text}.", outcome="deleted", data={"text": target.text})


def claim_voice(context: ToolContext, name: str) -> ToolResult:
    """Link the unknown voice to a name once the person or the owner confirms it."""
    state = context.state
    store = context.store
    claim = store.add_voice_claim(name, state.unknown_embedding)
    state.claimed_names.add(name)
    state.pending_name = None
    logger.info("Voice claim {} created", claim.id)
    if claim.person_id is None:
        return ToolResult(
            f"{name}, dich gibt es bei mir noch nicht. Im Kontrollzentrum kann man dich hinzufügen, "
            "dann erkenne ich dich.",
            outcome="claimed",
        )
    return ToolResult(
        f"Bestätige deine Stimme bitte einmal im Kontrollzentrum, {name}, dann erkenne ich dich.",
        outcome="claimed",
    )


async def introduce(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    state = context.state
    name = clean_name(text_argument(arguments, "name"))
    # "Gast" is how the action agent sees an unknown voice, not a name.
    if state is None or context.person is not None or not name or name.lower() in ("pebbo", "gast"):
        return ToolResult(outcome="ignored")
    # The action agent sometimes takes a guest who talks about Sara for Sara introducing herself.
    if state.last_utterance and not introduces_self(state.last_utterance, name):
        logger.info("A name was mentioned, but nobody introduced themselves")
        return ToolResult(outcome="ignored")
    known = context.store.find_similar_person(name)
    name = known.name if known else name
    if name in state.claimed_names:
        return ToolResult(outcome="pending")
    if state.unknown_embedding is None:
        state.pending_name = name
        logger.info("Introduction heard, waiting for enough speech to learn the voice")
        return ToolResult(
            f"Sag mir bitte noch einen Satz, {name}, damit ich mir deine Stimme merken kann.",
            outcome="waiting",
        )
    return claim_voice(context, name)


def register_memory_tools(registry: ToolRegistry) -> None:
    registry.register(
        Tool(
            name="remember",
            description=(
                "Merkt sich dauerhaft etwas über die sprechende Person: wenn sie darum bittet, oder wenn sie "
                "nebenbei etwas Dauerhaftes über sich erzählt (Vorlieben, Abneigungen, Familie, Freunde, "
                "Haustiere, Arbeit, Hobbys, Gewohnheiten, Geburtstage, Allergien, grössere Pläne). Nicht "
                "für Smalltalk, Stimmungen des Moments oder schon Bekanntes. Wenn sich etwas Bekanntes "
                "geändert hat, gib den alten Eintrag als replaces an."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Kurz und ohne Subjekt, z. B. 'Mag Kaffee ohne Zucker'",
                    },
                    "explicit": {
                        "type": "boolean",
                        "description": "true, wenn die Person ausdrücklich ums Merken gebeten hat",
                    },
                    "replaces": {
                        "type": "string",
                        "description": "Der bisherige Eintrag, der nicht mehr stimmt, sonst leer",
                    },
                },
                "required": ["text", "explicit"],
            },
            run=remember,
        )
    )
    registry.register(
        Tool(
            name="forget",
            description=(
                "Löscht etwas Gemerktes der sprechenden Person: wenn sie das möchte, oder wenn ein "
                "bekannter Eintrag nicht mehr stimmt."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "what": {
                        "type": "string",
                        "description": "Der Eintrag, der gelöscht werden soll, oder 'zuletzt'",
                    }
                },
                "required": ["what"],
            },
            run=forget,
        )
    )
    registry.register(
        Tool(
            name="introduce",
            description=(
                "Wenn eine noch unbekannte Stimme sagt, wie sie heisst, zum Beispiel 'ich bin Sara' oder "
                "'hier ist Tom'. Pebbo lernt dann die Stimme, nach einer Bestätigung im Kontrollzentrum."
            ),
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Der Vorname"}},
                "required": ["name"],
            },
            run=introduce,
            permission="everyone",
        )
    )
