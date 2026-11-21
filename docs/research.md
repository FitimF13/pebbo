# Research

Findings from the initial brainstorming in November 2026. Entries marked *to verify* still need a check against the upstream project before they are relied on. Licences apply to code. Model weights and voices often carry their own licences and must be checked separately.

## Voice pipeline candidates

| Stage | Candidates | Notes |
| --- | --- | --- |
| Wake word | [openWakeWord](https://github.com/dscripka/openWakeWord) (Apache-2.0), microWakeWord (runs on ESP32) | A custom "Hey Pebbo" can be trained from synthetic speech. Proprietary engines are avoided. |
| Voice activity | Silero VAD (MIT) | Standard choice, runs on CPU |
| Turn detection | Pipecat Smart Turn v3 | Small model that decides when a person has finished speaking, runs on CPU. *to verify* licence and German quality |
| Speech recognition | faster-whisper or whisper.cpp (MIT) with large-v3-turbo, NVIDIA Canary or Parakeet multilingual models | Whisper handles German well on a GPU. Small streaming models for the always-on box need a German benchmark. |
| Speech synthesis | Chosen: [Pocket TTS](https://github.com/kyutai-labs/pocket-tts) (MIT code, CC BY 4.0 weights, German since May 2026, streams on two CPU cores). Alternatives: Qwen3-TTS (Apache-2.0, German, GPU), Chatterbox Multilingual (MIT) | Piper moved to GPL-3.0 and many German voices are non-commercial. Kokoro has no strong German voice. Voxtral TTS weights are non-commercial. Online voices such as Edge TTS violate local first. |
| Speaker identification | SpeechBrain ECAPA, WeSpeaker (Apache-2.0) | Embeddings for voice fingerprints |
| Orchestration | [Pipecat](https://github.com/pipecat-ai/pipecat) (BSD-2), LiveKit Agents (Apache-2.0), Home Assistant Assist with Wyoming | Pipecat handles streaming, interruptions and local services |

### Full-duplex speech models

Full-duplex models listen and speak at the same time and handle backchannels natively. The best open model found, [NemotronLabs VoiceChat](https://huggingface.co/nvidia/NVIDIA-NemotronLabs-VoiceChat-11B), resumes after backchannels in most cases but is English only and needs about 9 GB even at 4-bit. Kyutai Moshi is English and French. Qwen Omni and MiniCPM-o models are candidates to test for German. *to verify* Re-evaluate every few months.

## Language models

| Option | Notes |
| --- | --- |
| Local on the gaming PC (RTX 4070 laptop, 8 GB) | Ollama or llama.cpp with models around 4B to 12B parameters, quantised |
| Small fallback on the always-on box | Around 1B to 2B parameters on an N100. *to verify* speed |
| Free API tiers (Groq, Google Gemini, OpenRouter, Mistral) | Rate limits. Some free tiers may use data for training. External, opt-in only. |
| Claude subscription | Since February 2026 Anthropic's terms allow subscription tokens only in Claude Code and Claude.ai, not in other tools or the Agent SDK. API keys are the supported path. ([report](https://winbuzzer.com/2026/02/19/anthropic-bans-claude-subscription-oauth-in-third-party-apps-xcxwbn/)) A later claim of relaxed rules is unconfirmed. *to verify* |
| Codex subscription | OpenAI documents a [Codex app server](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server) that custom clients can drive with the user's own ChatGPT sign-in. *to verify* that a personal assistant use case is covered by the terms. |

Agent harness candidates: a thin custom loop, [Pi](https://github.com/earendil-works/pi) with Pi Durable (crash-safe sessions with SQLite storage, experimental), Pydantic AI, OpenAI Agents SDK. Chosen: Pydantic AI, see [decisions](decisions.md). No framework makes a Claude subscription usable outside Claude Code and Claude.ai.

## Memory

| Option | Notes |
| --- | --- |
| Own layer on SQLite with sqlite-vec | Chosen direction: simple, one file per instance, easy to inspect and back up |
| mem0 (Apache-2.0) | Automatic fact extraction. Its hosted API must stay off. |
| Letta (Apache-2.0) | A full agent with memory, heavier |
| Graphiti, Zep | Temporal knowledge graphs, powerful but complex |
| Markdown files (for example Basic Memory) | Human readable, easy to audit |

## Smart home hubs

| Hub | Licence | Notes |
| --- | --- | --- |
| [Home Assistant](https://github.com/home-assistant/core) | Apache-2.0 | Chosen. Fully local, controls the Hue Bridge on the local network, built-in voice pipeline and MCP server. |
| openHAB | EPL-2.0 | Mature and local, smaller community |
| ioBroker | MIT | Popular in German-speaking countries |
| Hue Bridge directly | Proprietary bridge, local API | Lights only |

## Music

[Music Assistant](https://github.com/music-assistant/server) (Apache-2.0) supports Spotify, YouTube Music and players such as Cast, AirPlay, Sonos and DLNA. In early 2026 there were reports of a Spotify playlist API change and an unstable YouTube Music provider. *to verify* current status. Fallback: the Spotify Web API with Spotify Connect (Premium required).

## Calendars

| Source | Protocol | Notes |
| --- | --- | --- |
| Own calendar | Local CalDAV server such as [Radicale](https://github.com/Kozea/Radicale) | GPL-3.0, runs as a separate process |
| iCloud | CalDAV with an app-specific password | External, opt-in |
| Google Calendar | Google Calendar API with OAuth | External, opt-in, needs an own OAuth client |
| Microsoft 365 | Microsoft Graph with OAuth | External, opt-in, work accounts may need admin approval |

## Phone apps

- **Reference:** the [T3 Code mobile app](https://github.com/pingdotgg/t3code/tree/main/apps/mobile) uses Expo with React Native, native stack navigation (React Navigation and react-native-screens), Reanimated, Gesture Handler, Keyboard Controller, expo-glass-effect, expo-symbols, expo-haptics, expo-blur, @expo/ui, expo-notifications, expo-secure-store, expo-widgets and Uniwind (Tailwind for React Native). A good template for a modern native feel.
- **Builds:** [Codemagic](https://codemagic.io) builds and signs iOS and Android apps in the cloud. It is an external service used only for building, never at runtime.
- **App Store review:** the published app needs a demo mode with a synthetic Pebbo, a privacy policy and clear permission texts for the microphone and notifications.
- **Android push without Google:** [UnifiedPush](https://unifiedpush.org) with a self-hostable distributor such as ntfy. Firebase Cloud Messaging as a fallback.

## Remote access and push

- [Headscale](https://github.com/juanfont/headscale) (BSD-3): self-hosted coordination server for a private WireGuard network, can run on the VPS.
- An outbound tunnel from the home box to the VPS is a simpler alternative.
- Web Push works on iOS for web apps installed on the home screen. Payloads are end-to-end encrypted.
- ntfy (Apache-2.0) is an optional self-hosted push channel.

## Always-on box classes

| Class | Rough price (new) | Local model and speech |
| --- | --- | --- |
| Intel N100 or N150 | 150 to 250 | Chosen budget class. Core and Home Assistant easily. Only a very small fallback model and light speech recognition. |
| Raspberry Pi 5, 8 GB | Similar | Generally slower than an N100 |
| Apple Mac mini M4, 16 to 24 GB | 600 to 900 | 4B to 8B models and Whisper run well |
| AMD Ryzen mini PC with a strong iGPU, 32 GB | 500 to 900 | 4B to 8B models at usable speed *to verify* |
| NVIDIA Jetson Orin Nano Super, 8 GB | About 250 to 300 | Small models and Whisper on its GPU, ARM |
| AMD Ryzen AI Max, 64 to 128 GB | 1500 and more | Large models |

Prices are approximate.

## Device options (for phase 7)

| Option | Notes |
| --- | --- |
| ESP32-S3 board with display, microphones, speaker and LED ring | Cheap (roughly 20 to 50 per unit), low power, all intelligence on the core. Firmware in C or C++ with LVGL for the face. Preferred direction. |
| Raspberry Pi 5 or similar with a 2.1 to 2.8 inch display | Runs Linux, but costs more, gets warmer and needs a bigger case |

Reference designs: [Xiaozhi firmware](https://github.com/78/xiaozhi-esp32) (MIT), [Stack-chan](https://github.com/stack-chan/stack-chan) (Apache-2.0), [dotty-stackchan](https://github.com/BrettKinny/dotty-stackchan), Home Assistant Voice satellites.

## Existing projects reviewed

| Project | Verdict |
| --- | --- |
| [Xiaozhi ESP32](https://github.com/78/xiaozhi-esp32) and its [server](https://github.com/xinnan-tech/xiaozhi-esp32-server) | Closest to the concept. A local test showed that the server contacts a geo-IP service and a weather API by default. Documentation and memory prompts are mostly in Chinese. Reference only for firmware and the device protocol. |
| [Stack-chan](https://github.com/stack-chan/stack-chan), [dotty-stackchan](https://github.com/BrettKinny/dotty-stackchan) | References for a cute desk robot body and face |
| Home Assistant Assist and Wyoming | Good for the smart home and voice satellites. No personality or memory layer. |
| [Pipecat](https://github.com/pipecat-ai/pipecat) | Strong candidate for the voice pipeline |
| [Music Assistant](https://github.com/music-assistant/server) | Strong candidate for music |
| [OpenClaw](https://github.com/openclaw/openclaw) | Chat-first assistant with memory and many channels. A serious security issue in 2026 and a broad attack surface. Not suitable as the home core. |
