"""Pebbo decides after every sentence which tools to use while it answers, and confirms after."""

import asyncio
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pipecat.frames.frames import (
    Frame,
    InterruptionFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TTSSpeakFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection

from pebbo import clock
from pebbo.store import Store
from pebbo.tools.registry import GUEST_UNKNOWN, ContextSource, ToolResult
from pebbo.voice import assistant
from pebbo.voice.actions import decision_message, known_block, parse_tool_calls, recent_lines
from pebbo.voice.assistant import ActionGate, PersonalContext, confirmation
from pebbo.voice.honesty import HonestSpeech
from pebbo.voice.session import ConversationState

Decision = list[tuple[str, dict[str, Any]]]


@pytest.fixture
def store() -> Store:
    return Store(":memory:")


def capture(processor: Any, into: list[Frame]) -> None:
    async def push(frame: Frame, _direction: FrameDirection = FrameDirection.DOWNSTREAM) -> None:
        into.append(frame)

    processor.push_frame = push


class Conversation:
    """Runs PersonalContext and the ActionGate with a scripted decision instead of the model."""

    def __init__(self, store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
        self.state = ConversationState(store, recognizer=None)
        self.speech = HonestSpeech()
        self.gate = ActionGate()
        self.processor = PersonalContext(
            self.state, "http://127.0.0.1:11434", "test", speech=self.speech, gate=self.gate
        )
        self.context = LLMContext()
        self.pushed: list[Frame] = []
        self.through_gate: list[Frame] = []
        self.decision: Decision = []
        self.seen: list[dict[str, Any]] = []

        def decide(
            _url: str,
            _model: str,
            _tools: Any,
            messages: Any,
            name: str,
            facts: Any,
            reminders: Any,
            devices: Any = (),
        ) -> Decision:
            self.seen.append(
                {"lines": recent_lines(messages, name), "facts": list(facts), "devices": list(devices)}
            )
            return self.decision

        capture(self.processor, self.pushed)
        capture(self.gate, self.through_gate)
        monkeypatch.setattr(assistant, "choose_actions", decide)

    def say(self, text: str, decision: Decision, answer: str = "Gern!") -> list[str]:
        """Say a sentence, let the model answer ``answer``, and return what Pebbo speaks after it."""
        self.decision = decision
        self.context.add_message({"role": "user", "content": text})
        self.through_gate.clear()

        async def run() -> None:
            await self.processor._handle_context(LLMContextFrame(self.context), FrameDirection.DOWNSTREAM)
            for frame in (LLMFullResponseStartFrame(), LLMTextFrame(answer), LLMFullResponseEndFrame()):
                await self.gate.process_frame(frame, FrameDirection.DOWNSTREAM)
            await self.processor.wait_for_decisions()

        asyncio.run(run())
        return [frame.text for frame in self.through_gate if isinstance(frame, TTSSpeakFrame)]

    def handle(self) -> None:
        asyncio.run(self.processor._handle_context(LLMContextFrame(self.context), FrameDirection.DOWNSTREAM))


def test_facts_mentioned_in_passing_are_learned_quietly(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    conversation = Conversation(store, monkeypatch)
    conversation.state.person = store.add_person("Alex", "owner")

    spoken = conversation.say(
        "Mein Bruder Leon kommt am Wochenende",
        [("remember", {"text": "Bruder heisst Leon", "explicit": False})],
    )

    memories = store.memories(conversation.state.person.id)
    assert [(m.text, m.source) for m in memories] == [("Bruder heisst Leon", "learned")]
    assert spoken == [] and conversation.speech.filter("Gemerkt!") == ""


def test_the_answer_waits_for_the_decision_and_the_confirmation_follows_it(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    conversation = Conversation(store, monkeypatch)
    alex = conversation.state.person = store.add_person("Alex", "owner")
    store.add_memory(alex.id, "fact", "Trinkt Kaffee mit Zucker")

    spoken = conversation.say(
        "Ich trinke meinen Kaffee jetzt ohne Zucker",
        [
            (
                "remember",
                {"text": "Trinkt Kaffee ohne Zucker", "explicit": True, "replaces": "Kaffee mit Zucker"},
            )
        ],
    )

    assert [m.text for m in store.memories(alex.id)] == ["Trinkt Kaffee ohne Zucker"]
    assert spoken == ["Alles klar, geändert: Trinkt Kaffee ohne Zucker."]
    kinds = [type(frame).__name__ for frame in conversation.through_gate]
    assert kinds.index("TTSSpeakFrame") > kinds.index("LLMFullResponseEndFrame")
    assert conversation.seen[0]["facts"] == ["Trinkt Kaffee mit Zucker"]
    assert any(isinstance(frame, LLMContextFrame) for frame in conversation.pushed)


def test_another_voice_does_not_see_what_the_person_before_said(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    conversation = Conversation(store, monkeypatch)
    dropped: list[tuple[str, list[str]]] = []
    conversation.processor.on_history_dropped = lambda person, messages: dropped.append(
        (person.name, [m["content"] for m in messages])
    )
    sara = conversation.state.person = store.add_person("Sara", "owner")
    conversation.say("Merk dir, dass ich Kaffee ohne Zucker trinke", [])
    conversation.context.add_message({"role": "assistant", "content": "Gemerkt: Kaffee ohne Zucker."})
    conversation.say("Und erinnere mich an den Tee", [])
    conversation.context.add_message({"role": "assistant", "content": "Mach ich!"})
    assert dropped == []

    conversation.state.person = None  # A guest speaks now.
    conversation.say("Wie trinkt Sara ihren Kaffee?", [])

    spoken = [m["content"] for m in assistant.conversation_messages(conversation.context)]
    assert spoken == ["Wie trinkt Sara ihren Kaffee?"]
    assert "Kaffee ohne Zucker" not in conversation.seen[-1]["lines"]
    assert dropped == [
        (
            "Sara",
            [
                "Merk dir, dass ich Kaffee ohne Zucker trinke",
                "Gemerkt: Kaffee ohne Zucker.",
                "Und erinnere mich an den Tee",
                "Mach ich!",
            ],
        )
    ]
    assert conversation.state.history_owner is None and conversation.state.history_guest

    # When Sara speaks again, the guest's turns go too: they must not end up in her summary
    # (the test summarised a guest's "Ich trinke gern Pfefferminztee" as Sara's preference).
    conversation.context.add_message({"role": "assistant", "content": "Das weiss ich nicht."})
    conversation.state.person = sara
    conversation.say("Danke Pebbo", [])
    assert [m["content"] for m in assistant.conversation_messages(conversation.context)] == ["Danke Pebbo"]
    assert conversation.state.history_owner == sara.id and len(dropped) == 1


def test_the_gate_holds_the_answer_until_released() -> None:
    gate = ActionGate()
    passed: list[Frame] = []
    capture(gate, passed)

    async def run() -> None:
        turn = gate.hold()
        await gate.process_frame(LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM)
        await gate.process_frame(LLMTextFrame("Hoi!"), FrameDirection.DOWNSTREAM)
        assert passed == []
        await gate.release(turn, "Hab ich mir gemerkt: Mag Tee.")
        assert [type(frame).__name__ for frame in passed] == ["LLMFullResponseStartFrame", "LLMTextFrame"]
        await gate.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
        assert isinstance(passed[-1], TTSSpeakFrame)
        stale = gate.hold()
        await gate.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
        await gate.release(stale, "zu spät")
        assert not any(isinstance(frame, TTSSpeakFrame) and frame.text == "zu spät" for frame in passed)

    asyncio.run(run())


def test_each_sentence_is_decided_once_with_the_lines_before(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    conversation = Conversation(store, monkeypatch)
    conversation.state.person = store.add_person("Alex", "owner")

    conversation.say("Hallo Pebbo", [])
    conversation.context.add_message({"role": "assistant", "content": "Hoi Alex!"})
    conversation.say("Vergiss das wieder", [])
    conversation.handle()

    assert len(conversation.seen) == 2
    assert conversation.seen[1]["lines"] == (
        "Davor im Gespräch:\nAlex: Hallo Pebbo\nPebbo: Hoi Alex!\n\n"
        "Letzte Äusserung von Alex, nur darum geht es:\nVergiss das wieder"
    )


def test_guests_hear_why_nothing_is_stored(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    conversation = Conversation(store, monkeypatch)

    assert conversation.say("Ich mag Tee", [("remember", {"text": "Mag Tee", "explicit": False})]) == []
    request: Decision = [("remember", {"text": "Mag Tee", "explicit": True})]
    assert conversation.say("Merk dir, dass ich Tee mag", request) == [GUEST_UNKNOWN]
    assert conversation.say("Merk dir, dass ich Tee mag", request) == [GUEST_UNKNOWN]
    assert store.all_memories() == []


def test_model_replies_are_parsed_defensively() -> None:
    reply = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {"function": {"name": "nothing", "arguments": "{}"}},
                        {"function": {"name": "forget", "arguments": '{"what": "zuletzt"}'}},
                        {"function": {"name": "remember", "arguments": "{kaputt"}},
                    ]
                }
            }
        ]
    }
    assert parse_tool_calls(reply) == [("forget", {"what": "zuletzt"})]
    assert "noch nichts" in known_block("Alex", [], [])


def test_a_correction_is_confirmed_as_one_change() -> None:
    deleted = ToolResult("Okay, vergessen: Mag Tee.", outcome="deleted", data={"text": "Mag Tee"})
    stored = ToolResult("Hab ich mir gemerkt: Mag Kaffee.", outcome="stored", data={"text": "Mag Kaffee"})
    assert confirmation([("forget", deleted), ("remember", stored)]) == "Alles klar, geändert: Mag Kaffee."
    assert confirmation([("forget", deleted)]) == "Okay, vergessen: Mag Tee."
    quiet = ToolResult("", outcome="stored")
    assert confirmation([("remember", quiet), ("remember", stored), ("remember", stored)]) == stored.say


def test_a_failing_decision_still_lets_the_answer_through(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    conversation = Conversation(store, monkeypatch)
    conversation.state.person = store.add_person("Alex", "owner")

    def broken(*_args: Any) -> Decision:
        raise OSError("model offline")

    monkeypatch.setattr(assistant, "choose_actions", broken)
    assert conversation.say("Merk dir, dass ich Tee mag", []) == []
    assert any(isinstance(frame, LLMTextFrame) for frame in conversation.through_gate)


def test_the_decision_sees_the_devices_of_household_members_only(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Without the device names and rooms the agent called HassTurnOn(name="Wohnzimmer").
    conversation = Conversation(store, monkeypatch)

    async def devices(_context: Any) -> str:
        return "Geräte im Haus:\n- Bereich Wohnzimmer:\n  - Stehlampe: an"

    conversation.processor._agent._registry.add_context(ContextSource("mcp:Test", devices))
    conversation.say("Mach das Licht aus", [])
    assert conversation.seen[-1]["devices"] == []
    conversation.state.person = store.add_person("Alex", "owner")
    conversation.say("Mach das Licht aus", [])
    assert conversation.seen[-1]["devices"] == ["Geräte im Haus:\n- Bereich Wohnzimmer:\n  - Stehlampe: an"]
    message = decision_message([{"role": "user", "content": "x"}], "Alex", devices=["- Stehlampe: an"])
    assert "- noch nichts\n\n- Stehlampe: an\n\nLetzte Äusserung" in message


@pytest.mark.parametrize("name", ["Alex", "Gast"])
def test_the_decision_knows_the_date_for_everyone(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # "morgen um acht" needs today's date. Without it the model guessed a date in the past.
    moment = datetime(2026, 11, 21, 12, 58, tzinfo=ZoneInfo("Europe/Zurich"))
    monkeypatch.setattr(clock, "now", lambda: moment)
    message = decision_message([{"role": "user", "content": "Erinnere mich morgen um acht"}], name)
    assert message.startswith("Jetzt ist 2026-11-21T12:58+01:00, Samstag.")
    assert ("Es spricht Alex." in message) == (name == "Alex")
