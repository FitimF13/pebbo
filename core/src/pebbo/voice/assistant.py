"""What the language model knows in a conversation, and how Pebbo acts on it.

Before each answer Pebbo adds a context message: the time, who is speaking, what Pebbo
knows about that person and their open reminders. The conversation model only talks. After
each sentence the action agent (``pebbo.voice.actions``) picks tools from the registry
(``pebbo.tools``), the registry checks the permissions and the tools run. Pebbo's answer is
then generated knowing what really happened.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any, Literal, cast

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    InterruptionFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TTSSpeakFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext, LLMContextMessage
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from pebbo import clock
from pebbo.briefing import personal_lines
from pebbo.store import Person
from pebbo.tools import builtin_tools
from pebbo.tools.memory import claim_voice, known_facts
from pebbo.tools.registry import ToolContext, ToolRegistry, ToolResult
from pebbo.voice.actions import GUEST, choose_actions
from pebbo.voice.honesty import HonestSpeech
from pebbo.voice.persona import SYSTEM_PROMPT
from pebbo.voice.session import ConversationState

CONTEXT_MARKER = "[Pebbo-Kontext]"
# Transcripts are personal. They are logged only when the owner turns this on for troubleshooting.
TRANSCRIPT_LEVEL = "INFO" if os.environ.get("PEBBO_LOG_TRANSCRIPTS") == "1" else "DEBUG"
ACTIONS_RULE = (
    "Was Pebbo tut, also merken, vergessen, Erinnerungen planen, Termine eintragen, Geräte schalten, Musik "
    "abspielen und mehr, passiert nach deiner Antwort von selbst und wird danach kurz bestätigt. Behaupte "
    "nie, du hättest etwas gemerkt, gelöscht, geplant, geschaltet oder ausgeführt, schreib keine Notizen "
    "darüber und sprich nie von einem System. Bei einer Bitte reicht ein kurzes 'Gern!' oder 'Mach ich!'."
)
# Without a device list from an integration such as Home Assistant, Pebbo cannot switch anything.
NO_DEVICES_RULE = "Geräte im Haus kannst du noch nicht steuern. Sag das ehrlich, wenn jemand darum bittet."
KNOWLEDGE_RULE = (
    "Über Menschen weisst du nur, was hier steht. Erfinde nie Erinnerungen, Eigenschaften oder Erlebnisse "
    "von jemandem. Wenn du etwas nicht weisst, frag nach oder sag es ehrlich."
)
ROLE_NAMES = {"owner": "Besitzer", "adult": "erwachsen", "child": "Kind", "colleague": "Kollege"}
_MAX_FACTS = 30
_MAX_SUMMARIES = 3
# Pebbo answers without acting rather than keep someone waiting longer than this.
_DECISION_TIMEOUT_SECONDS = 5.0
# Pebbo answers without the tool sources' context (such as device states) rather than wait longer.
_SOURCE_CONTEXT_TIMEOUT_SECONDS = 1.5


def context_message(
    state: ConversationState,
    reference: datetime | None = None,
    extra: Sequence[str] = (),
    channel: Literal["voice", "app"] = "voice",
) -> str:
    """Build the per-turn context for the speaking person, or for a guest.

    ``extra`` holds what tool sources add for a recognised person, for example the current
    state of the devices. It is never shown to guests. ``channel`` is "app" when the person
    writes in the phone app instead of speaking.
    """
    lines = [CONTEXT_MARKER, f"Jetzt ist {clock.describe_now(reference)}."]
    person = state.person
    if person is None:
        lines += [
            "Du erkennst die Menschen im Haushalt an ihrer Stimme. Diese Stimme hast du gerade nicht "
            "sicher erkannt, du sprichst also mit einem Gast. Wenn jemand fragt, ob du ihn erkennst, sag das "
            "ehrlich und dass du die Stimme nach ein, zwei weiteren Sätzen meist erkennst.",
            "Wenn sich jemand mit Namen vorstellt, begrüsse die Person mit Namen. Wie es mit der Stimme "
            "weitergeht, wird danach von selbst gesagt.",
            "Gästen gibst du keine persönlichen Informationen, Erinnerungen oder Termine weiter. "
            "Für Gäste merkst du dir nichts und planst nichts, versprich das auch nicht.",
            "Über andere Menschen weisst du in diesem Gespräch nichts. Fragt der Gast nach jemand anderem, "
            "sag kurz und freundlich, dass du über andere nichts erzählst. Erfinde nie etwas über Menschen.",
            KNOWLEDGE_RULE,
        ]
        return "\n".join(lines)
    role = ROLE_NAMES.get(person.role, person.role)
    if channel == "app":
        lines.append(
            f"{person.name} ({role}) schreibt dir gerade in der Pebbo-App auf dem Handy. "
            "Jede Nachricht ist an dich gerichtet, antworte also immer."
        )
    else:
        lines.append(f"Wer gerade mit dir spricht, ist {person.name} ({role}). Du hast die Stimme erkannt.")
    facts = known_facts(state.store, person.id)[:_MAX_FACTS]
    household = [m.text for m in state.store.memories(None)][:_MAX_FACTS]
    summaries = [m.text for m in state.store.memories(person.id, kind="summary")][:_MAX_SUMMARIES]
    reminders = state.store.reminders(person.id)
    if facts:
        lines.append(f"Was du über {person.name} weisst. Nutze es, wenn eine Frage dazu passt:")
        lines += [f"- {fact}" for fact in facts]
    if household:
        lines.append("Was du über den Haushalt weisst:")
        lines += [f"- {fact}" for fact in household]
    if summaries:
        lines.append("Worüber ihr zuletzt gesprochen habt:")
        lines += [f"- {summary}" for summary in summaries]
    if reminders:
        lines.append("Offene Erinnerungen:")
        zone = clock.timezone()
        lines += [
            f"- {clock.spoken_datetime(datetime.fromtimestamp(r.due_at, zone), reference)}: {r.text}"
            for r in reminders
        ]
    lines += personal_lines(state.store, person, reference)
    sources = [text for text in extra if text]
    lines += sources or [NO_DEVICES_RULE]
    lines += [KNOWLEDGE_RULE, ACTIONS_RULE]
    return "\n".join(lines)


def user_messages(context: LLMContext) -> list[dict[str, Any]]:
    """All user turns with text content, oldest first."""
    return [
        cast("dict[str, Any]", message)
        for message in context.get_messages()
        if isinstance(message, dict)
        and message.get("role") == "user"
        and isinstance(message.get("content"), str)
    ]


def user_texts(context: LLMContext) -> list[str]:
    """The texts of all user turns in the conversation, oldest first."""
    return [str(message["content"]) for message in user_messages(context)]


def confirmation(results: list[tuple[str, ToolResult]]) -> str:
    """What Pebbo says after its tools ran: their sentences, with a correction said as one."""
    return " ".join(confirmation_sentences(results))


def confirmation_sentences(results: list[tuple[str, ToolResult]]) -> list[str]:
    """The tools' sentences in order, without repeats, with a correction said as one."""
    deleted = [r for name, r in results if name == "forget" and r.outcome == "deleted"]
    stored = [r for name, r in results if name == "remember" and r.outcome == "stored" and r.say]
    sentences: list[str] = []
    for _name, result in results:
        if not result.say or (stored and any(result is r for r in deleted)):
            continue
        say = result.say
        if deleted and any(result is r for r in stored):
            say = f"Alles klar, geändert: {result.data.get('text', '')}."
        if say not in sentences:
            sentences.append(say)
    return sentences


class SpokenAnswer:
    """The sentences Pebbo synthesised since the person's last turn.

    Pipecat adds a sentence to the context only once it has been played to its end. When the
    person interrupts the first sentence, the context then holds two questions in a row and
    the model answers the old one again. :class:`PersonalContext` puts what Pebbo had begun to
    say back between them.
    """

    def __init__(self) -> None:
        self._sentences: list[str] = []

    def add(self, text: str) -> None:
        self._sentences.append(text.strip())

    def take(self) -> str:
        """What was said since the last call, and start over."""
        text, self._sentences = " ".join(s for s in self._sentences if s), []
        return text


class ActionGate(FrameProcessor):
    """Holds Pebbo's answer back until the action agent has decided, then adds what was done.

    Sits right after the language model. Deciding and answering run at the same time, so a
    sentence without actions costs no extra time. The answer starts speaking once the
    decision is in, and the tools' short confirmation follows the answer, never in the middle
    of it.
    """

    _ANSWER = (LLMFullResponseStartFrame, LLMTextFrame, LLMFullResponseEndFrame)

    def __init__(self) -> None:
        super().__init__()
        self._turn = 0
        self._holding = False
        self._held: list[tuple[Frame, FrameDirection]] = []
        self._answer_ended = False
        self._after: str = ""

    def hold(self) -> int:
        """Hold the next answer. Returns the turn to pass to :meth:`release`."""
        self._turn += 1
        self._holding, self._held, self._answer_ended, self._after = True, [], False, ""
        return self._turn

    async def release(self, turn: int, say: str = "") -> None:
        """Let the held answer through and say ``say`` after it."""
        if turn != self._turn or not self._holding:
            return
        self._holding = False
        held, self._held = self._held, []
        for frame, direction in held:
            await self.push_frame(frame, direction)
        if say and self._answer_ended:
            await self.push_frame(TTSSpeakFrame(say))
        else:
            self._after = say

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, InterruptionFrame):
            self._holding, self._held, self._after = False, [], ""
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, self._ANSWER):
            if isinstance(frame, LLMFullResponseEndFrame):
                self._answer_ended = True
            if self._holding:
                self._held.append((frame, direction))
                return
            await self.push_frame(frame, direction)
            if isinstance(frame, LLMFullResponseEndFrame) and self._after:
                say, self._after = self._after, ""
                await self.push_frame(TTSSpeakFrame(say))
            return
        await self.push_frame(frame, direction)


class ActionAgent:
    """Decides after a sentence which tools to use, and runs them with the registry's permissions.

    Used by the voice conversation (:class:`PersonalContext`) and by the text chat of the
    phone app (``pebbo.chat``), so both act the same way.
    """

    def __init__(
        self,
        state: ConversationState,
        llm_base_url: str = "",
        decision_model: str = "",
        registry: ToolRegistry | None = None,
    ) -> None:
        self._state = state
        self._decider = (llm_base_url, decision_model)
        self._registry = registry or builtin_tools()

    async def source_context(self) -> list[str]:
        """What the tool sources add to the context, for example device states. Never for guests."""
        person = self._state.person
        if person is None:
            return []
        try:
            return await asyncio.wait_for(
                self._registry.context(ToolContext(self._state.store, person, self._state)),
                _SOURCE_CONTEXT_TIMEOUT_SECONDS,
            )
        except Exception:  # The answer goes on without it.
            logger.warning("Context from the tool sources is unavailable")
            return []

    async def act(
        self, person: Person | None, messages: list[dict[str, Any]]
    ) -> list[tuple[str, ToolResult]]:
        """Decide what to do after a sentence and do it."""
        tool_context = ToolContext(self._state.store, person, self._state)
        last = messages[-1] if messages else {}
        if last.get("role") == "user" and isinstance(last.get("content"), str):
            self._state.last_utterance = last["content"]
        results: list[tuple[str, ToolResult]] = []
        pending = self._claim_pending_name(tool_context)
        if pending is not None:
            results.append(("introduce", pending))
        if all(self._decider):
            for name, arguments in await self._decide(person, messages):
                results.append((name, await self._registry.call(name, arguments, tool_context)))
        if results:
            logger.info("Actions: {}", ", ".join(f"{name} ({result.outcome})" for name, result in results))
        return results

    async def _decide(
        self, person: Person | None, messages: list[dict[str, Any]]
    ) -> list[tuple[str, dict[str, Any]]]:
        store = self._state.store
        facts = known_facts(store, person.id)[:_MAX_FACTS] if person else []
        reminders = [r.text for r in store.reminders(person.id)] if person else []
        # The device names and rooms, so the agent switches the right device. Never for guests.
        devices = await self.source_context() if person else []
        started = time.monotonic()
        try:
            actions = await asyncio.wait_for(
                asyncio.to_thread(
                    choose_actions,
                    self._decider[0],
                    self._decider[1],
                    self._registry.schemas(),
                    messages,
                    person.name if person else GUEST,
                    facts,
                    reminders,
                    devices,
                ),
                _DECISION_TIMEOUT_SECONDS,
            )
        except Exception:  # The conversation goes on without the action.
            logger.exception("Could not decide on actions")
            return []
        logger.debug("Decided in {:.2f} s", time.monotonic() - started)
        return actions

    def _claim_pending_name(self, context: ToolContext) -> ToolResult | None:
        """A name heard before the voice was long enough to learn is claimed on a later turn."""
        state = self._state
        if not state.is_guest:
            state.pending_name = None
            return None
        name = state.pending_name
        if name is None or state.unknown_embedding is None or name in state.claimed_names:
            return None
        return claim_voice(context, name)


class PersonalContext(FrameProcessor):
    """Puts Pebbo's context message into the conversation and acts on each sentence.

    After every sentence the action agent decides which tools to use while the language
    model already answers (Ollama runs both at once). The :class:`ActionGate` holds the answer
    until the decision is in, and the tools' short factual sentences are spoken right after
    it. The answer itself never claims an action (see ``pebbo.voice.honesty``).

    The context only ever holds one recognised person's conversation. When someone else
    speaks, the earlier turns are handed to ``on_history_dropped`` (to be summarised for
    that person) and removed, so a guest never hears what the person before said.
    """

    def __init__(
        self,
        state: ConversationState,
        llm_base_url: str = "",
        llm_model: str = "",
        decision_model: str = "",
        registry: ToolRegistry | None = None,
        speech: HonestSpeech | None = None,
        gate: ActionGate | None = None,
        on_history_dropped: Callable[[Person, list[dict[str, Any]]], None] | None = None,
        answer: SpokenAnswer | None = None,
    ) -> None:
        super().__init__()
        self._state = state
        self.on_history_dropped = on_history_dropped
        self._agent = ActionAgent(state, llm_base_url, decision_model or llm_model, registry)
        self._speech = speech
        self._gate = gate
        self._answer = answer
        # The user turn that was handled. A repeated sentence is a new turn and is handled
        # again, the same turn passing by a second time is not.
        self._handled: dict[str, Any] | None = None
        self._turn: dict[str, Any] | None = None
        self._background: set[asyncio.Task[None]] = set()

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame) and not frame.speculation:
            await self._handle_context(frame, direction)
            return
        await self.push_frame(frame, direction)

    async def _handle_context(self, frame: LLMContextFrame, direction: FrameDirection) -> None:
        await self._state.settled()
        messages = user_messages(frame.context)
        self._turn = messages[-1] if messages else None
        if self._turn is not None:
            logger.log(TRANSCRIPT_LEVEL, "User said: {}", self._turn["content"])
        if self._is_new_turn():
            self._keep_history_private(frame.context)
            self._restore_interrupted_answer(frame.context)
            turn = self._gate.hold() if self._gate is not None else 0
            if self._speech is not None:
                self._speech.allow_claims(False)
            task = asyncio.create_task(
                self._act_and_release(turn, self._state.person, conversation_messages(frame.context))
            )
            self._background.add(task)
            task.add_done_callback(self._background.discard)
        refresh(frame.context, context_message(self._state, extra=await self._agent.source_context()))
        await self.push_frame(frame, direction)

    async def wait_for_decisions(self) -> None:
        """Wait until the decisions still running in the background are done."""
        while self._background:
            await asyncio.gather(*self._background, return_exceptions=True)

    def _keep_history_private(self, context: LLMContext) -> None:
        """Remove the turns so far from the context when someone else speaks.

        A recognised person's turns are summarised for them first. A guest's turns are only
        dropped, so they never end up in the summary of the person who speaks next.
        """
        state, person = self._state, self._state.person
        owner = state.history_owner
        speaker = person.id if person is not None else None
        if (owner is not None and speaker != owner) or (state.history_guest and speaker is not None):
            earlier = [
                dict(m)
                for m in context.get_messages()
                if isinstance(m, dict) and not _is_context(m) and m is not self._turn
            ]
            context.set_messages([cast("LLMContextMessage", self._turn)] if self._turn is not None else [])
            previous = state.store.person(owner) if owner is not None else None
            logger.info("Another voice speaks, the conversation so far is set aside")
            if previous is not None and earlier and self.on_history_dropped is not None:
                self.on_history_dropped(previous, earlier)
        state.history_owner, state.history_guest = speaker, speaker is None

    def _restore_interrupted_answer(self, context: LLMContext) -> None:
        """Put an answer the person interrupted back before their new turn."""
        spoken = self._answer.take() if self._answer is not None else ""
        messages = context.get_messages()
        index = next((i for i, m in enumerate(messages) if m is self._turn), -1)
        earlier = [m for m in messages[:index] if isinstance(m, dict) and not _is_context(m)]
        if not spoken or not earlier or earlier[-1].get("role") != "user":
            return
        messages.insert(index, {"role": "assistant", "content": f"{spoken} …"})
        context.set_messages(messages)

    def _is_new_turn(self) -> bool:
        if self._turn is None or self._turn is self._handled:
            return False
        self._handled = self._turn
        return True

    async def _act_and_release(
        self, turn: int, person: Person | None, messages: list[dict[str, Any]]
    ) -> None:
        say = ""
        try:
            say = confirmation(await self._agent.act(person, messages))
        finally:
            if say and self._speech is not None:
                self._speech.allow(say)
            if self._gate is not None:
                await self._gate.release(turn, say)


def refresh(context: LLMContext, text: str) -> None:
    """Put the persona and the per-turn context into one system message at the start.

    Ministral's chat template keeps only one system message, so both go into the same one. The
    persona comes first: it never changes, so Ollama reuses it from its cache on every turn.
    """
    messages = [m for m in context.get_messages() if not _is_context(m)]
    context.set_messages([{"role": "system", "content": f"{SYSTEM_PROMPT}\n\n{text}"}, *messages])


def conversation_messages(context: LLMContext) -> list[dict[str, Any]]:
    """The conversation without Pebbo's context messages."""
    return [dict(m) for m in context.get_messages() if isinstance(m, dict) and not _is_context(m)]


def _is_context(message: Any) -> bool:
    content = message.get("content") if isinstance(message, dict) else None
    return isinstance(content, str) and (
        content.startswith(CONTEXT_MARKER) or content.startswith(f"{SYSTEM_PROMPT}\n\n{CONTEXT_MARKER}")
    )
