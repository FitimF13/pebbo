"""Load speech models once per process and share them between conversations."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
from functools import lru_cache
from typing import Any

import numpy as np
import pipecat.services.pocket_tts.tts as pocket_tts_service
from faster_whisper import WhisperModel
from loguru import logger
from pipecat.frames.frames import Frame, TranscriptionFrame
from pipecat.services.whisper.stt import WhisperSTTService
from pipecat.utils.time import time_now_iso8601
from pocket_tts import TTSModel

from pebbo.voice.wake import addresses_pebbo


class FastWhisperModel(WhisperModel):  # type: ignore[misc]
    """Whisper tuned for short spoken turns: greedy decoding and no carried-over context.

    Beam search (the default of five beams) roughly doubles the time per utterance and
    brings little for short, clear sentences.
    """

    def transcribe(self, audio: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("beam_size", 1)
        kwargs.setdefault("condition_on_previous_text", False)
        return super().transcribe(audio, **kwargs)


def has_cuda() -> bool:
    import ctranslate2

    try:
        return int(ctranslate2.get_cuda_device_count()) > 0
    except Exception:  # No CUDA runtime at all.
        return False


def speech_model(name: str, device: str, compute_type: str, cpu_name: str) -> tuple[str, str, str]:
    """Whisper model, device and precision for this computer: the large model on an NVIDIA GPU,
    a small one on the CPU of a computer without one."""
    if device == "cpu" or (device == "auto" and not has_cuda()):
        return cpu_name, "cpu", "int8"
    return name, device, compute_type


@lru_cache(maxsize=4)
def whisper_model(name: str, device: str, compute_type: str) -> WhisperModel:
    return FastWhisperModel(name, device=device, compute_type=compute_type)


@lru_cache(maxsize=4)
def _pocket_tts_model(language: str, quantize: bool, temp: float | None) -> Any:
    kwargs: dict[str, Any] = {"language": language, "quantize": quantize}
    if temp is not None:
        kwargs["temp"] = temp
    return TTSModel.load_model(**kwargs)


class _CachedPocketTTSModel:
    """Stands in for ``pocket_tts.TTSModel`` inside Pipecat's service and caches loaded models."""

    @staticmethod
    def load_model(*, language: str, quantize: bool = False, temp: float | None = None) -> Any:
        return _pocket_tts_model(language, quantize, temp)


pocket_tts_service.TTSModel = _CachedPocketTTSModel  # type: ignore[attr-defined]


# A second look for the wake phrase only makes sense for short utterances.
_SECOND_LOOK_MAX_SECONDS = 8


class SharedWhisperSTTService(WhisperSTTService):
    """Whisper speech recognition that reuses an already loaded model.

    The name "Pebbo" is passed to Whisper as a hotword, which helps in most sentences. When
    the name is said quickly ("Hey Pebbo, merk dir ..."), Whisper sometimes drops it
    together with the greeting because of that same hotword. While Pebbo sleeps, an
    utterance that does not seem to address Pebbo is therefore transcribed a second time
    without the hotword before it is ignored.
    """

    asleep: Callable[[], bool] | None = None

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        frames = [frame async for frame in super().run_stt(audio)]
        transcripts = [frame for frame in frames if isinstance(frame, TranscriptionFrame)]
        text = transcripts[0].text if transcripts else ""
        logger.debug("Transcribed {:.1f} s of speech", len(audio) / 32_000)
        if self._needs_second_look(audio, text):
            plain = await asyncio.to_thread(self._transcribe_plain, audio)
            logger.debug("Second look for the wake phrase: {}", plain)
            if addresses_pebbo(plain):
                if transcripts:
                    transcripts[0].text = plain
                else:
                    frames.append(TranscriptionFrame(plain, self._user_id, time_now_iso8601(), None))
        for frame in frames:
            if isinstance(frame, TranscriptionFrame):
                # Whisper transcribes a whole segment at once, so each transcript is final. Saying
                # so lets the turn end right away instead of after the STT safety timeout (1 s).
                frame.finalized = True
            yield frame

    def _needs_second_look(self, audio: bytes, text: str) -> bool:
        if self.asleep is None or not self.asleep() or self._model is None:
            return False
        return len(audio) <= _SECOND_LOOK_MAX_SECONDS * 16_000 * 2 and not addresses_pebbo(text)

    def _transcribe_plain(self, audio: bytes) -> str:
        samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = self._model.transcribe(samples, language=self._settings.language)  # type: ignore[union-attr,attr-defined]
        return " ".join(segment.text.strip() for segment in segments)

    def _load(self) -> None:
        model_name = str(self._settings.model)  # type: ignore[attr-defined]
        self._model = whisper_model(model_name, self._device, self._compute_type)
        unsupported = self._unsupported_language()
        if unsupported:
            raise ValueError(unsupported)


def preload(whisper_name: str, whisper_device: str, whisper_compute_type: str, tts_language: str) -> None:
    """Load the speech models before the first conversation starts."""
    whisper_model(whisper_name, whisper_device, whisper_compute_type)
    _pocket_tts_model(tts_language, False, None)
