# Third-party models and voices

Pebbo downloads these models once and then runs them locally. Each keeps its own licence. Attribution for the CC BY licensed parts is given here.

| Component | Used for | Licence | Source |
| --- | --- | --- | --- |
| Whisper large-v3-turbo (CTranslate2 conversion) | Speech recognition | MIT | [OpenAI](https://huggingface.co/openai/whisper-large-v3-turbo) |
| Pocket TTS, German model | Speech synthesis | Code MIT, weights CC BY 4.0, © Kyutai | [Kyutai](https://github.com/kyutai-labs/pocket-tts) |
| Voice "vera" (VCTK speaker p229) | Pebbo's default voice | CC BY 4.0, from the [CSTR VCTK Corpus](https://datashare.ed.ac.uk/handle/10283/3443), University of Edinburgh | [kyutai/tts-voices](https://huggingface.co/kyutai/tts-voices) |
| Voice "alba" (Alba MacKenna, casual) | Alternative voice | CC BY 4.0, voice acted by Alba MacKenna | [kyutai/tts-voices](https://huggingface.co/kyutai/tts-voices) |
| Ministral 3 8B Instruct | Answers | Apache-2.0, © Mistral AI | [Mistral AI](https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512) |
| CAM++ speaker embedding model (3D-Speaker, VoxCeleb) | Speaker recognition | Apache-2.0 | [sherpa-onnx releases](https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models) |
| Silero VAD | Voice activity detection | MIT | [Silero](https://github.com/snakers4/silero-vad) |
| Smart Turn v3 | End-of-turn detection | BSD-2-Clause | [Pipecat](https://huggingface.co/pipecat-ai/smart-turn-v3) |

## Software for integrations

| Component | Used for | Licence | Source |
| --- | --- | --- | --- |
| MCP Python SDK (`mcp`, `mcp-types`) | Client for MCP servers such as Home Assistant. Contacts only the servers the owner configured. Its OpenTelemetry tracing is only the API without an exporter, so it records and sends nothing. | MIT | [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk) |
| httpx2 | HTTP client of the MCP SDK. Pebbo turns off proxies from the environment for it. | BSD-3-Clause | [PyPI](https://pypi.org/project/httpx2/) |
| jsonschema, referencing, rpds-py, PyJWT | Dependencies of the MCP SDK | MIT | PyPI |
| sse-starlette | Dependency of the MCP SDK (server side, unused by Pebbo) | BSD-3-Clause | PyPI |
| pywin32 | Dependency of the MCP SDK on Windows | PSF | PyPI |

Home Assistant and Music Assistant run as separate programs and are not bundled.

## Software for the phone app and the control centre

| Component | Used for | Licence | Source |
| --- | --- | --- | --- |
| Expo SDK 58 (`expo`, `expo-secure-store`, `expo-haptics`, `expo-status-bar`, `expo-system-ui`, `expo-build-properties`) | Phone app framework, token storage in Keychain and Keystore, haptics. The Expo CLI runs only through `apps/mobile/scripts/expo.mjs` with `EXPO_NO_TELEMETRY=1` and `EXPO_OFFLINE=1`. expo-updates and expo-dev-client are not used, so the app has no update or account service. | MIT | [expo/expo](https://github.com/expo/expo) |
| React Native 0.88 | Native app runtime | MIT | [facebook/react-native](https://github.com/facebook/react-native) |
| React Navigation 7 (`@react-navigation/native`, `@react-navigation/bottom-tabs`) | Tabs in the app | MIT | [react-navigation](https://github.com/react-navigation/react-navigation) |
| react-native-screens, react-native-safe-area-context | Native screens and safe areas | MIT | [software-mansion](https://github.com/software-mansion/react-native-screens), [th3rdwave](https://github.com/th3rdwave/react-native-safe-area-context) |
| react-native-svg | Pebbo's face and icons in the app | MIT | [software-mansion/react-native-svg](https://github.com/software-mansion/react-native-svg) |
| uqr | Drawing the pairing QR code in the control centre, locally | MIT | [unjs/uqr](https://github.com/unjs/uqr) |

The app has no in-app QR scanner: expo-camera scans codes on Android with Google ML Kit, which may contact Google's servers and send usage metrics. The phone's own camera app opens the pairing link instead (see [phone app](phone.md#what-the-app-contacts)).

## Software for the body and the case

| Component | Used for | Licence | Source |
| --- | --- | --- | --- |
| xiaozhi-esp32 firmware | Firmware of Pebbo bodies, built with Pebbo's board code | MIT | [78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) |
| ESP-IDF | Building the firmware | Apache-2.0 | [Espressif](https://github.com/espressif/esp-idf) |
| PyAV (FFmpeg with libopus) | Opus audio for bodies in the core | BSD-3-Clause, bundled FFmpeg LGPL-2.1 | [PyAV](https://github.com/PyAV-Org/PyAV) |
| build123d | Building the case (development only) | Apache-2.0 | [build123d](https://github.com/gumyr/build123d) |
| VTK | Case preview images (development only) | BSD-3-Clause | [VTK](https://vtk.org) |

Voices in the Kyutai voice collection marked as non-commercial (Expresso, EARS) must not be used as Pebbo defaults.

## Licence check of the dependencies

Checked on 2026-11-21 with the installed packages of the core and `pnpm licenses list --prod`:

- The web app's runtime dependencies are MIT licensed. The libraries the phone app uses at runtime (listed above) are MIT licensed. The Expo CLI and Metro, which build the phone app, bring build tools under other permissive licences (Apache-2.0, BSD, ISC, BlueOak-1.0.0, 0BSD, Unlicense, CC0, CC BY 4.0 for the caniuse-lite data, Python-2.0 for argparse), lightningcss (MPL-2.0, unmodified) and node-forge (BSD-3-Clause or GPL-2.0, used under BSD-3-Clause). None of these build tools ends up in the app (checked on 2026-11-21 with `pnpm licenses list --prod --filter @pebbo/mobile`).
- All Python dependencies are under permissive licences (MIT, BSD, Apache-2.0, ISC, PSF and similar), with two exceptions that are allowed:
  - `num2words` (LGPL), used unmodified as a library by the speech pipeline. Pebbo does not bundle or change it.
  - NVIDIA's CUDA runtime packages (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`, `nvidia-cuda-nvrtc-cu12`, NVIDIA licence), installed only with the optional `gpu` extra on the user's machine and never redistributed by Pebbo.
- No GPL code is bundled. The firmware's own licence (MIT) and the hardware licence (CERN-OHL-P v2) are compatible with the Apache-2.0 code.

## Development aids

| Component | Used for | Licence | Source |
| --- | --- | --- | --- |
| Matt Pocock's skills (27 skills in `.agents/skills/`) | Instructions for coding agents working on this repository: grilling, specs and tickets, TDD, code review, debugging and more. Text only; not part of Pebbo. | MIT | [mattpocock/skills](https://github.com/mattpocock/skills) |

