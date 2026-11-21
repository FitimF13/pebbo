"""How a conversation flows: ending turns, holding on, interruptions and summaries."""

import asyncio
from typing import Any

import pytest
from pipecat.frames.frames import Frame, InterruptionFrame, LLMContextFrame, TranscriptionFrame
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection
from pipecat.utils.asyncio.task_manager import TaskManager

from pebbo.store import Store
from pebbo.voice.assistant import PersonalContext, SpokenAnswer, conversation_messages
from pebbo.voice.backchannel import BackchannelAwareTurnStartStrategy, SpokenTextMemory, is_hold_command
from pebbo.voice.session import ConversationState
from pebbo.voice.summary import parse_summary, worth_summarising
from pebbo.voice.turn_end import TranscriptTurnStopStrategy


@pytest.mark.parametrize("text", ["Warte mal", "Moment bitte", "Warte, warte!", "Moment mal kurz"])
def test_hold_on_commands(text: str) -> None:
    assert is_hold_command(text)


@pytest.mark.parametrize(
    "text", ["Nein", "Warte, ich will noch was sagen", "Stopp", "Einen Moment lang dachte ich"]
)
def test_other_sentences_are_no_hold_on_commands(text: str) -> None:
    assert not is_hold_command(text)


def test_hold_on_stops_pebbo_without_an_answer() -> None:
    strategy = BackchannelAwareTurnStartStrategy(spoken=SpokenTextMemory())
    calls: list[str] = []

    async def broadcast(frame_cls: type[Frame], **_kwargs: Any) -> None:
        calls.append(frame_cls.__name__)

    async def reset() -> None:
        calls.append("reset")

    async def started(**_kwargs: Any) -> None:
        calls.append("turn")

    strategy.broadcast_frame = broadcast  # type: ignore[method-assign]
    strategy.trigger_reset_aggregation = reset  # type: ignore[method-assign]
    strategy.report_user_turn_started = started  # type: ignore[method-assign]

    asyncio.run(strategy.process_frame(TranscriptionFrame("Warte mal", "user", "now")))
    assert calls == [InterruptionFrame.__name__, "reset"]
    asyncio.run(strategy.process_frame(TranscriptionFrame("Wie spät ist es?", "user", "now")))
    assert calls[-1] == "turn"


class _Analyzer:
    """Stands in for Smart Turn, which the strategy only stores here."""


def stop_strategy() -> tuple[TranscriptTurnStopStrategy, list[str]]:
    strategy = TranscriptTurnStopStrategy(turn_analyzer=_Analyzer())  # type: ignore[arg-type]
    stopped: list[str] = []

    async def report(**_kwargs: Any) -> None:
        stopped.append("stopped")

    strategy.report_user_turn_stopped = report  # type: ignore[method-assign]
    return strategy, stopped


def test_a_turn_started_from_a_finished_sentence_ends_with_its_transcript() -> None:
    strategy, stopped = stop_strategy()
    # Speech already ended and Smart Turn found the sentence complete. The transcript then
    # starts the turn (wake phrase and backchannel strategies decide on transcripts).
    strategy._vad_stopped, strategy._turn_complete = True, True

    async def run() -> None:
        await strategy.handle_user_turn_started()
        await strategy.process_frame(TranscriptionFrame("Wie spät ist es?", "user", "now", finalized=True))

    asyncio.run(run())
    assert stopped == ["stopped"]


def test_an_unfinished_sentence_still_waits_for_more_speech() -> None:
    strategy, stopped = stop_strategy()
    strategy._vad_stopped, strategy._turn_complete = True, False

    async def run() -> None:
        strategy._task_manager = TaskManager(loop=asyncio.get_running_loop())
        await strategy.handle_user_turn_started()
        strategy._stt_timeout = 1.0  # Pipecat's default safety window for the rest of the sentence
        await strategy.process_frame(TranscriptionFrame("Merk dir bitte", "user", "now", finalized=True))
        assert stopped == [] and strategy._timeout_task is not None
        await strategy.task_manager.cancel_task(strategy._timeout_task)

    asyncio.run(run())


def test_an_interrupted_answer_stays_in_the_conversation() -> None:
    state = ConversationState(Store(":memory:"), recognizer=None)
    answer = SpokenAnswer()
    processor = PersonalContext(state, answer=answer)

    async def push(_frame: Frame, _direction: FrameDirection = FrameDirection.DOWNSTREAM) -> None:
        return None

    processor.push_frame = push  # type: ignore[method-assign,assignment]
    context = LLMContext()

    def say(text: str) -> None:
        context.add_message({"role": "user", "content": text})
        asyncio.run(processor._handle_context(LLMContextFrame(context), FrameDirection.DOWNSTREAM))

    say("Was empfiehlst du mir zum Mittagessen?")
    # Pebbo starts to answer and is interrupted before the sentence is played to its end, so
    # Pipecat never adds it to the context.
    answer.add("Eine Rösti mit Spiegelei wäre perfekt.")
    say("Wie spät ist es eigentlich?")

    assert [(m["role"], m["content"]) for m in conversation_messages(context)] == [
        ("user", "Was empfiehlst du mir zum Mittagessen?"),
        ("assistant", "Eine Rösti mit Spiegelei wäre perfekt. …"),
        ("user", "Wie spät ist es eigentlich?"),
    ]

    # A finished answer is already in the context and is not added twice.
    context.add_message({"role": "assistant", "content": "Kurz nach eins."})
    answer.add("Kurz nach eins.")
    say("Danke")
    assert len(conversation_messages(context)) == 5


def test_summaries_keep_the_text_around_the_empty_marker() -> None:
    assert parse_summary("LEER") is None
    assert parse_summary(" leer. ") is None
    assert parse_summary("") is None
    assert (
        parse_summary("Sara plant einen **Kinobesuch** mit Leon. LEER")
        == "Sara plant einen Kinobesuch mit Leon."
    )
    # At temperature 0 the model sometimes adds a list with a heading; only the summary stays.
    assert (
        parse_summary(
            "Sara bittet um eine Erinnerung für ihren Tee. Sie trinkt Kaffee ohne Zucker. Pebbo mag das. "
            "Nützlich für spätere Gespräche: - Gewohnheiten: Sara trinkt Kaffee ohne Zucker."
        )
        == "Sara bittet um eine Erinnerung für ihren Tee. Sie trinkt Kaffee ohne Zucker."
    )
    assert parse_summary("Sara geht ins Kino.\n\n- Vorliebe: Kino") == "Sara geht ins Kino."


def test_only_conversations_with_content_are_summarised() -> None:
    def said(*texts: str) -> list[dict[str, Any]]:
        return [{"role": "user", "content": text} for text in texts]

    assert not worth_summarising(said("Hey Pebbo, wie geht's dir heute?", "Danke, tschüss!"))
    assert worth_summarising(said("Hey Pebbo", "Ich gehe heute Abend mit Leon ins Kino"))
    assert worth_summarising(said("Merk dir, dass ich Kaffee ohne Zucker trinke"))
