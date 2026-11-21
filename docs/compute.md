# Compute devices and the always-on box

Pebbo's language model can run on several computers. The owner lists them in the control centre, tab **Rechner**, in the order Pebbo should try them. Pebbo checks every 20 seconds which ones answer and starts each new conversation on the first reachable one. If the gaming PC is switched off, Pebbo carries on with the next computer, usually a smaller model with simpler answers, and switches back when the gaming PC is on again.

## Typical setup

| Computer | Runs | Model |
| --- | --- | --- |
| Always-on mini PC (the core) | Pebbo core, speech recognition on the CPU (Whisper `small`), Pocket TTS, Ollama | a small model, for example `ministral-3:3b` |
| Gaming PC (worker, optional) | Ollama only | `pebbo-ministral` (Ministral 3 8B) |

1. **On the gaming PC**, let Ollama accept connections from the home network: set the environment variable `OLLAMA_HOST=0.0.0.0` (and `OLLAMA_NUM_PARALLEL=2`), restart Ollama and allow it through the firewall for private networks. Create the Pebbo model there once with `uv run pebbo download-models` or `ollama create`.
2. **On the always-on box**, run the core as usual. Without an NVIDIA GPU, Pebbo automatically uses a small Whisper model on the CPU (`PEBBO_WHISPER_CPU_MODEL`, default `small`). Run `uv run pebbo download-models` once on the box so that model is there. Point `PEBBO_LLM_MODEL` at the box's small model.
3. **In the control centre**, tab **Rechner**, add the gaming PC with its address (for example `http://192.168.1.30`) and the model `pebbo-ministral`, and move it to the top. "Dieser Rechner" (the box) stays as the fallback.

Computers must be on the home network or a private VPN. Ollama has no sign-in, so it must never be reachable from the internet.

## What changes on the box alone

- Answers come from the small model: shorter and less nuanced. Memory, reminders, routines, devices and the app work the same, because they run in the core.
- Speech recognition on the CPU is slower (about one second for a short sentence on an N100-class CPU, to be measured) and less accurate.
- Routines and due reminders never need a language model.
