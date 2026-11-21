"""Command line entry point: ``pebbo serve`` and ``pebbo download-models``."""

from __future__ import annotations

import argparse
import os
import sys


def _serve() -> None:
    from pebbo.runtime import prepare_environment

    prepare_environment(offline=True)

    from pebbo import netguard

    netguard.install()

    import uvicorn
    from loguru import logger

    from pebbo.app import create_app
    from pebbo.config import ServerConfig, VoiceConfig
    from pebbo.models_router import ComputeDevice, ModelRouter
    from pebbo.people.speaker import MODEL_FILE, SpeakerRecognizer
    from pebbo.reminders import ReminderScheduler
    from pebbo.runtime import disable_onnxruntime_telemetry
    from pebbo.store import Store, default_data_dir
    from pebbo.voice.models import preload
    from pebbo.voice.ollama_setup import warm_up
    from pebbo.voice.pipeline import VoiceServices

    disable_onnxruntime_telemetry()
    logger.remove()
    logger.add(sys.stderr, level=os.environ.get("PEBBO_LOG_LEVEL", "INFO"))

    voice_config, server_config = VoiceConfig(), ServerConfig()
    data_dir = default_data_dir()
    store = Store(data_dir / "pebbo.sqlite3")
    speaker_model = data_dir / "models" / MODEL_FILE
    recognizer = SpeakerRecognizer(store, speaker_model) if speaker_model.exists() else None
    if recognizer is None:
        logger.warning("Voice recognition is off: run 'pebbo download-models' to get the speaker model.")
    default = ComputeDevice(0, "Dieser Rechner", voice_config.llm_base_url, voice_config.llm_model, 0)
    router = ModelRouter(store, default)
    router.refresh()
    services = VoiceServices(voice_config, store, ReminderScheduler(store), recognizer, router=router)
    logger.info("Data is stored in {}", data_dir)
    logger.info("Loading speech models and the language model")
    preload(*services.speech, "german")
    device = router.current()
    warm_up(device.base_url, device.model)
    logger.info("Pebbo is ready on http://{}:{}", server_config.host, server_config.port)
    uvicorn.run(
        create_app(services, server_config.web_dist),
        host=server_config.host,
        port=server_config.port,
        log_level="warning",
    )


def _download_models() -> None:
    from pebbo.runtime import MODEL_HOSTS, prepare_environment

    prepare_environment(offline=False)

    from pebbo import netguard

    netguard.install(MODEL_HOSTS)

    from pebbo.config import VoiceConfig
    from pebbo.voice.models import preload, speech_model

    config = VoiceConfig()
    speech = speech_model(
        config.whisper_model, config.whisper_device, config.whisper_compute_type, config.whisper_cpu_model
    )
    print(f"Downloading Whisper '{speech[0]}' and the German Pocket TTS model from Hugging Face ...")
    preload(*speech, "german")

    from pocket_tts import TTSModel

    TTSModel.load_model(language="german").get_state_for_audio_prompt(config.tts_voice)

    from pebbo.voice.ollama_setup import create_model

    print(f"Creating the Ollama model '{config.llm_model}' from '{config.llm_base_model}' ...")
    print(f"(Install the base model first with: ollama pull {config.llm_base_model})")
    create_model(config.llm_base_url, config.llm_model, config.llm_base_model)
    from pebbo.people.speaker import MODEL_FILE, MODEL_URL
    from pebbo.runtime import download
    from pebbo.store import default_data_dir

    target = default_data_dir() / "models" / MODEL_FILE
    if not target.exists():
        print("Downloading the speaker recognition model (CAM++, Apache-2.0) from GitHub ...")
        netguard.allow(("github.com", ".githubusercontent.com"))
        download(MODEL_URL, target)
    print("Done. Pebbo now loads these models offline.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="pebbo", description="Pebbo core service")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="Run the core with the voice pipeline")
    commands.add_parser("download-models", help="Download speech models once (needs internet)")
    arguments = parser.parse_args()
    if arguments.command == "serve":
        _serve()
    else:
        _download_models()


if __name__ == "__main__":
    main()
