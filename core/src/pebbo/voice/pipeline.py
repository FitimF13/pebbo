"""The voice conversation pipeline for one connected client."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import Frame, TTSSpeakFrame, TTSTextFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.frameworks.rtvi.frames import RTVIServerMessageFrame
from pipecat.services.ollama.llm import OLLamaLLMService
from pipecat.services.pocket_tts.tts import PocketTTSService
from pipecat.transcriptions.language import Language
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.turns.user_turn_strategies import StrategyMode, UserTurnStrategies, UserTurnStrategiesParams
from pipecat.workers.runner import WorkerRunner

from pebbo.config import VoiceConfig
from pebbo.models_router import ComputeDevice, ModelRouter
from pebbo.people.speaker import SpeakerRecognizer
from pebbo.reminders import ReminderScheduler
from pebbo.store import Person, Store
from pebbo.tools import builtin_tools
from pebbo.tools.registry import ToolRegistry
from pebbo.voice.assistant import (
    TRANSCRIPT_LEVEL,
    ActionGate,
    PersonalContext,
    SpokenAnswer,
    conversation_messages,
)
from pebbo.voice.backchannel import BackchannelAwareTurnStartStrategy, SpokenTextMemory
from pebbo.voice.emotion import EmotionTagProcessor
from pebbo.voice.honesty import HonestSpeech
from pebbo.voice.models import SharedWhisperSTTService, speech_model
from pebbo.voice.pitch import PitchShifter
from pebbo.voice.session import ConversationState
from pebbo.voice.speaker_tap import SpeakerTap
from pebbo.voice.speech_text import speech_transform
from pebbo.voice.summary import summarize, user_turns
from pebbo.voice.turn_end import TranscriptTurnStopStrategy
from pebbo.voice.wake import RECOGNITION_HOTWORDS, PebboWakeStrategy


class SpokenTextRecorder(FrameProcessor):
    """Remembers the words Pebbo speaks, so its own echo is not taken for the user.

    It also keeps the current answer, so an answer the person interrupts stays in the
    conversation (see :class:`SpokenAnswer`).
    """

    def __init__(self, memory: SpokenTextMemory, answer: SpokenAnswer | None = None) -> None:
        super().__init__()
        self._memory = memory
        self._answer = answer

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSTextFrame):
            self._memory.add(frame.text)
            if self._answer is not None:
                self._answer.add(frame.text)
            logger.log(TRANSCRIPT_LEVEL, "Pebbo said: {}", frame.text)
        await self.push_frame(frame, direction)


class VoiceServices:
    """Models that are loaded once and shared by all sessions."""

    def __init__(
        self,
        config: VoiceConfig,
        store: Store,
        scheduler: ReminderScheduler,
        recognizer: SpeakerRecognizer | None = None,
        registry: ToolRegistry | None = None,
        router: ModelRouter | None = None,
    ) -> None:
        self.config = config
        self.router = router
        if registry is None:
            from pebbo.routines.structure import llm_structurer

            registry = builtin_tools(llm_structurer(lambda: (self.device().base_url, self.device().model)))
        self.registry = registry
        self.speech = speech_model(
            config.whisper_model, config.whisper_device, config.whisper_compute_type, config.whisper_cpu_model
        )
        self.language = Language(config.language)
        self.store = store
        self.scheduler = scheduler
        self.recognizer = recognizer

    def stt(self) -> SharedWhisperSTTService:
        name, device, compute_type = self.speech
        return SharedWhisperSTTService(
            device=device,
            compute_type=compute_type,
            settings=SharedWhisperSTTService.Settings(
                model=name,
                language=self.language,
                hotwords=RECOGNITION_HOTWORDS,
            ),
        )

    def tts(self, honest: HonestSpeech) -> PocketTTSService:
        return PocketTTSService(
            settings=PocketTTSService.Settings(voice=self.config.tts_voice, language=self.language),
            text_transforms=[("*", honest.transform), ("*", speech_transform)],
        )

    def device(self) -> ComputeDevice:
        """The compute device for a new conversation."""
        if self.router is not None:
            return self.router.current()
        return ComputeDevice(0, "Dieser Rechner", self.config.llm_base_url, self.config.llm_model, 0)

    def llm(self, device: ComputeDevice) -> OLLamaLLMService:
        return OLLamaLLMService(
            base_url=device.base_url,
            settings=OLLamaLLMService.Settings(
                model=device.model,
                max_completion_tokens=160,
            ),
        )


def webrtc_transport(connection: SmallWebRTCConnection) -> SmallWebRTCTransport:
    return SmallWebRTCTransport(
        webrtc_connection=connection,
        params=TransportParams(audio_in_enabled=True, audio_out_enabled=True),
    )


Events = Callable[[dict[str, str]], Awaitable[None]]
WakeHandler = Callable[[], Awaitable[None]]


async def run_conversation(
    transport: BaseTransport,
    services: VoiceServices,
    events: Events | None = None,
    on_wake_handler: Callable[[WakeHandler], None] | None = None,
) -> None:
    """Run one conversation until the client disconnects.

    Args:
        transport: The PC app's WebRTC connection or a body's WebSocket.
        services: The shared models and the database.
        events: Where face events go. By default they go to the PC app as RTVI messages.
        on_wake_handler: Receives a function that wakes Pebbo, for clients with their own
            wake word.
    """
    config = services.config
    device = services.device()
    if device.id != 0:
        logger.info("Thinking on {}", device.name)
    spoken = SpokenTextMemory()
    answer = SpokenAnswer()
    honest = HonestSpeech()
    gate = ActionGate()
    state = ConversationState(services.store, services.recognizer)
    worker: PipelineWorker | None = None
    background: set[asyncio.Task[None]] = set()

    async def send(data: dict[str, str]) -> None:
        if events is not None:
            await events(data)
        elif worker is not None:
            await worker.queue_frames([RTVIServerMessageFrame(data=data)])

    async def on_emotion(emotion: str) -> None:
        await send({"type": "emotion", "emotion": emotion})

    async def speak(text: str) -> None:
        """Say something Pebbo starts on its own, for example a due reminder."""
        if worker is not None:
            await send({"type": "emotion", "emotion": "curious"})
            honest.allow(text)
            await worker.queue_frames([TTSSpeakFrame(text)])

    def summarise_later(person: Person, messages: list[dict[str, Any]]) -> None:
        """Keep a short summary of a conversation for the person it belongs to."""
        if user_turns(messages) == 0:
            return

        async def store_summary() -> None:
            try:
                text = await asyncio.to_thread(
                    summarize, device.base_url, device.model, messages, person.name
                )
            except Exception:
                logger.exception("Could not summarise the conversation")
                return
            if text:
                services.store.add_memory(person.id, "summary", text, source="summary")
                services.store.prune_summaries(person.id)
                logger.info("Stored a conversation summary for person {}", person.id)

        task = asyncio.create_task(store_summary())
        background.add(task)
        task.add_done_callback(background.discard)

    async def end_conversation() -> None:
        """Summarise the finished conversation and start the next one fresh."""
        messages = conversation_messages(context)
        # Only a recognised person's conversation is kept. Guests' small talk is not.
        person = state.history_person()
        context.set_messages([])
        state.reset()
        if person is not None:
            summarise_later(person, messages)

    stt = services.stt()
    start_strategies: list[object] = [BackchannelAwareTurnStartStrategy(spoken=spoken)]
    if config.require_wake_phrase:
        wake = PebboWakeStrategy(timeout=config.conversation_timeout)
        stt.asleep = lambda: wake.asleep

        @wake.event_handler("on_wake_phrase_detected")
        async def on_wake(_strategy: object, _phrase: str) -> None:
            logger.info("Wake phrase detected")
            await send({"type": "wake", "state": "awake"})

        @wake.event_handler("on_wake_phrase_timeout")
        async def on_sleep(_strategy: object) -> None:
            logger.info("Conversation ended")
            await send({"type": "wake", "state": "asleep"})
            await end_conversation()

        start_strategies.insert(0, wake)

        async def wake_from_client() -> None:
            wake.wake_up()

        if on_wake_handler is not None:
            on_wake_handler(wake_from_client)

    context = LLMContext()
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            # Short pauses keep answers fast. PebboWakeStrategy joins a split "Hey Pebbo, ...".
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
            user_turn_strategies=UserTurnStrategies(
                start=start_strategies,  # type: ignore[arg-type]
                stop=[TranscriptTurnStopStrategy(turn_analyzer=LocalSmartTurnAnalyzerV3())],
            ),
            user_turn_strategies_params=UserTurnStrategiesParams(start_mode=StrategyMode.ALL),
        ),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            SpeakerTap(state),
            stt,
            user_aggregator,
            PersonalContext(
                state,
                device.base_url,
                device.model,
                config.decision_model if device.id == 0 else "",
                registry=services.registry,
                speech=honest,
                gate=gate,
                on_history_dropped=summarise_later,
                answer=answer,
            ),
            services.llm(device),
            gate,
            EmotionTagProcessor(on_emotion),
            services.tts(honest),
            PitchShifter(config.tts_pitch),
            SpokenTextRecorder(spoken, answer),
            transport.output(),
            assistant_aggregator,
        ]
    )
    worker = PipelineWorker(pipeline, params=PipelineParams(enable_metrics=True))
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)

    @transport.event_handler("on_client_connected")
    async def on_connected(_transport: object, _client: object) -> None:
        logger.info("Client connected")
        await send({"type": "wake", "state": "asleep" if config.require_wake_phrase else "awake"})
        services.scheduler.connect(speak)
        await services.scheduler.deliver_due()

    @transport.event_handler("on_client_disconnected")
    async def on_disconnected(_transport: object, _client: object) -> None:
        logger.info("Client disconnected")
        services.scheduler.disconnect(speak)
        await end_conversation()
        await runner.cancel()

    await runner.run()
