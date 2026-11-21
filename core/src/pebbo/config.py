"""Configuration from environment variables with local defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    return os.environ.get(f"PEBBO_{name}", default)


@dataclass(frozen=True)
class VoiceConfig:
    """Settings for the voice pipeline."""

    language: str = field(default_factory=lambda: _env("LANGUAGE", "de"))
    whisper_model: str = field(default_factory=lambda: _env("WHISPER_MODEL", "large-v3-turbo"))
    whisper_device: str = field(default_factory=lambda: _env("WHISPER_DEVICE", "auto"))
    whisper_compute_type: str = field(default_factory=lambda: _env("WHISPER_COMPUTE_TYPE", "int8_float16"))
    # Used instead when there is no NVIDIA GPU, for example on an always-on mini PC.
    whisper_cpu_model: str = field(default_factory=lambda: _env("WHISPER_CPU_MODEL", "small"))
    tts_voice: str = field(default_factory=lambda: _env("TTS_VOICE", "vera"))
    # Raises pitch and tempo of the voice by this factor, for example 1.1 for a cuter sound.
    tts_pitch: float = field(default_factory=lambda: float(_env("TTS_PITCH", "1.0")))
    llm_base_url: str = field(default_factory=lambda: _env("LLM_BASE_URL", "http://127.0.0.1:11434/v1"))
    # Ollama model that "pebbo download-models" derives from llm_base_model with a small context.
    llm_base_model: str = field(default_factory=lambda: _env("LLM_BASE_MODEL", "ministral-3:8b"))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "pebbo-ministral"))
    # Model that decides after each sentence what to remember or plan. Empty means llm_model.
    decision_model: str = field(default_factory=lambda: _env("DECISION_MODEL", ""))
    conversation_timeout: float = field(default_factory=lambda: float(_env("CONVERSATION_TIMEOUT", "20")))
    require_wake_phrase: bool = field(default_factory=lambda: _env("REQUIRE_WAKE_PHRASE", "1") == "1")


@dataclass(frozen=True)
class ServerConfig:
    """Settings for the HTTP server."""

    host: str = field(default_factory=lambda: _env("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(_env("PORT", "8100")))
    web_dist: str | None = field(default_factory=lambda: os.environ.get("PEBBO_WEB_DIST"))
    # This instance's name, for example "Zuhause" or "Büro", shown to the other instance.
    instance_name: str = field(default_factory=lambda: _env("INSTANCE_NAME", "Zuhause"))
    # The address other instances use to reach this one. Empty: http://<host>:<port>.
    public_url: str = field(default_factory=lambda: _env("PUBLIC_URL", ""))

    def own_address(self) -> str:
        return self.public_url or f"http://{self.host}:{self.port}"
