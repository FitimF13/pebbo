# Running Pebbo on a PC

Phase 1 runs the whole conversation on one PC: the core with speech recognition, the language model and speech synthesis, and the PC app in the browser.

## Requirements

- Windows or Linux with an NVIDIA GPU with 8 GB of memory (tested on an RTX 4070 laptop GPU). Speech synthesis runs on the CPU.
- [uv](https://docs.astral.sh/uv/), Node.js 22.13 or newer with Corepack, and [Ollama](https://ollama.com).
- A microphone and speakers or headphones. Headphones avoid echo, but echo cancellation in the browser and Pebbo's echo filter also work with speakers.

## One-time setup (needs internet)

```sh
corepack enable
pnpm install
pnpm --filter @pebbo/web build

cd core
uv sync --extra gpu
ollama pull ministral-3:8b
uv run pebbo download-models
```

`pebbo download-models` downloads Whisper and the German Pocket TTS model from Hugging Face, the CAM++ speaker recognition model from the sherpa-onnx releases on GitHub, and creates the Ollama model `pebbo-ministral` with a small context window. During this step the network guard allows only these hosts.

Let Ollama answer two requests at once, so Pebbo can decide what to do while it answers: set the user environment variable `OLLAMA_NUM_PARALLEL=2` and restart Ollama (on Windows: quit the Ollama tray app and start it again).

## Start

```sh
cd core
PEBBO_WEB_DIST=../apps/web/dist uv run pebbo serve
```

On Windows PowerShell: `$env:PEBBO_WEB_DIST = "..\apps\web\dist"; uv run pebbo serve`.

Open <http://127.0.0.1:8100>, click **Pebbo aufwecken** and allow the microphone. Then say "Hey Pebbo" and talk.

## First use: people and voices

1. Open the control centre with the button in the top right corner (or <http://127.0.0.1:8100/#/kontrollzentrum>) and enter your first name. You become the owner. Invite other household members there.
2. Wake Pebbo and introduce yourself, in any words: "Hey Pebbo, ich bin Sara." Pebbo asks you to confirm your voice. A request appears at the top of the control centre. Confirm it. If Pebbo has heard too little of your voice, it asks for one more sentence first. A misheard name ("sarah", "Zara") is matched to the closest household member.
3. From then on Pebbo recognises your voice and gets better with every sentence. Unknown voices are treated as guests: they can chat, but Pebbo does not store or reveal anything personal for them. If a guest asks Pebbo to remember or plan something, Pebbo says that it needs a name or a confirmed voice first. When a guest joins your conversation, Pebbo sets aside what you said before, so the guest does not hear it.

## Memory and reminders

Pebbo has no command words. After every sentence it decides from the conversation whether to use one of its tools, and confirms in its own words what it did.

- "Merk dir, dass ich Kaffee ohne Zucker trinke" stores a fact for the person speaking. "Vergiss das" removes the last one. "Ich trinke ihn jetzt ohne Zucker" updates the old fact.
- Lasting things mentioned in passing ("Mein Bruder Leon spielt Fussball") are stored quietly. The control centre marks them as learned in passing.
- "Erinnere mich in zehn Minuten an den Tee" or "Erinnere mich morgen früh ans Training" plans a reminder. "Morgen früh" means 07:30, "heute Abend" 19:00. Pebbo says the reminder out loud when it is due. If no PC app is connected at that moment, it says it as soon as one connects.
- Saying the same thing twice does not store it twice. A fact that is almost the same as a stored one, or a reminder for the same task within ten minutes of an open one, is recognised and not stored again.
- When a conversation ends, Pebbo keeps a one- or two-sentence summary for the person, so it knows what you talked about.
- The control centre shows everything per person and lets you delete or add entries and cancel reminders.
- All of this is stored in one local database (`%LOCALAPPDATA%\Pebbo\pebbo.sqlite3` on Windows, `~/.local/share/pebbo/` on Linux, or `PEBBO_DATA_DIR`). Voices are stored as numeric fingerprints, never as recordings.

## Routines, calendar and the morning briefing

Details and more examples are in [routines, calendar and the morning briefing](routines.md).

- "Jeden Werktag um sieben sagst du mir guten Morgen" or "Wenn ich gehe und niemand mehr da ist, sag tschüss" teaches a routine. Pebbo reads it back and saves it only after your yes. "Probier es jetzt" shows what it would do, without doing it.
- Routines run in the core even when no language model is available. Spoken routines need a connected PC app or body and stay silent during quiet hours.
- "Trag mir morgen um neun den Zahnarzt ein" adds an appointment, "Was habe ich morgen?" reads a day. Today's appointments are part of Pebbo's context for the recognised person.
- The first time Pebbo recognises you on a day (from 05:00), it offers a short overview of the day if something is planned.
- The control centre has the tabs **Routinen** (pause, resume, approve, test, delete, run log) and **Kalender** (appointments and read-only ICS subscriptions). A subscription outside the home network is contacted only after you switch on "Externen Host erlauben" for it.

## Smart home and music

Pebbo controls lights, switches and media players through Home Assistant's MCP server, and music through Music Assistant inside Home Assistant. Add Home Assistant in the control centre, tab **Integrationen**, with its address (for example `http://192.168.1.20:8123/api/mcp/assist`) and a long-lived access token. Then say what you want, in any words: "Mach das Licht im Wohnzimmer an", "Ist die Stehlampe noch an?" or "Pause die Musik". Pebbo knows the current state of the exposed devices for recognised household members, never for guests. MCP servers must be on the home network unless the owner explicitly allows a public address. See [smart home and music](smart-home.md) for the step-by-step setup.

## A Pebbo body

The physical Pebbo (an ESP32-S3-BOX-3 in a printed case) connects to the running core over Wi-Fi and pairs with a code shown on its screen. See [Pebbo bodies](devices.md) and the [hardware](../hardware/README.md).

## The phone app

Start the core with `PEBBO_HOST=0.0.0.0`, open the control centre, go to **Geräte** and create a code for a person under **Handys**. Scan the QR code with the phone's camera to open the Pebbo app, or type the address and the code in the app. The phone then chats with Pebbo as that person and shows their reminders and memories. Building and installing the app is described in [phone app](phone.md#building-the-app).

## For smooth conversations

- Speech recognition and the language model share the GPU. Close other GPU-heavy programs (for example Blender, games or video editors) while talking to Pebbo. With less than about 1.5 GB of free GPU memory, Windows moves model memory to system RAM and answers can take many seconds.
- Run the laptop on power and in its performance mode (on Lenovo Legion laptops Fn+Q until the performance mode is shown). Power-saving modes limit the GPU to a fraction of its speed.

## What to expect

- Pebbo sleeps until it hears "Hey Pebbo". After that, the conversation stays open for 20 seconds after the last activity, so follow-up questions need no wake phrase.
- "Stopp", "Halt" or "Ruhe" end the conversation at once. "Tschüss" or "Gute Nacht" end it after a short goodbye. The power button in the app disconnects Pebbo, the microphone button mutes it.
- When people talk to each other near Pebbo, it stays silent if the sentence is clearly not meant for it.
- "Mhm", "ja" or "genau" while Pebbo talks or thinks do not interrupt it. A real sentence does, and Pebbo answers it; if you cut Pebbo off, it remembers what it had begun to say. "Warte mal" or "Moment" on its own stops Pebbo without an answer, so you can go on.
- The face shows sleeping, listening, thinking and the emotion of each answer, and the mouth follows the voice.
- Nothing leaves the PC: models load offline, telemetry of all libraries is switched off and the network guard blocks any connection to a public address. MCP servers such as Home Assistant are reached only on the home network, unless the owner allowed a public address for a server, and a calendar subscription reaches an external host only after you allowed it in the control centre.

## Settings

Environment variables, all optional:

| Variable | Default | Meaning |
| --- | --- | --- |
| `PEBBO_PORT` | `8100` | HTTP port |
| `PEBBO_HOST` | `127.0.0.1` | Interface to listen on. `0.0.0.0` lets Pebbo bodies and paired phones on the home network connect; the control centre still answers only on this computer. See [Pebbo bodies](devices.md) and [phone app](phone.md). |
| `PEBBO_APP_ADDRESS` | detected | Address of this core that the pairing QR code gives to phones, for example `http://pebbo.local:8100` |
| `PEBBO_WEB_DIST` | none | Built PC app to serve at `/` |
| `PEBBO_LLM_MODEL` | `pebbo-ministral` | Ollama model for answers |
| `PEBBO_LLM_BASE_MODEL` | `ministral-3:8b` | Model that `download-models` derives `pebbo-ministral` from |
| `PEBBO_LLM_BASE_URL` | `http://127.0.0.1:11434/v1` | Local Ollama endpoint |
| `PEBBO_WHISPER_MODEL` | `large-v3-turbo` | Whisper model |
| `PEBBO_WHISPER_CPU_MODEL` | `small` | Whisper model used on computers without an NVIDIA GPU, see [compute devices](compute.md) |
| `PEBBO_WHISPER_COMPUTE_TYPE` | `int8_float16` | Whisper precision on the GPU |
| `PEBBO_TTS_VOICE` | `vera` | Pocket TTS voice, see [third-party models](third-party.md) |
| `PEBBO_TTS_PITCH` | `1.0` | Raises pitch and tempo of the voice, for example `1.1` for a cuter sound |
| `PEBBO_CONVERSATION_TIMEOUT` | `20` | Seconds a conversation stays open after the last activity |
| `PEBBO_REQUIRE_WAKE_PHRASE` | `1` | Set to `0` to talk without "Hey Pebbo" |
| `PEBBO_DATA_DIR` | see above | Where the database and downloaded speaker model live |
| `PEBBO_INSTANCE_NAME` | `Zuhause` | Name of this instance, see [two Pebbos](office.md) |
| `PEBBO_PUBLIC_URL` | `http://<host>:<port>`, with `PEBBO_HOST=0.0.0.0` the detected home network address | Address another instance uses to reach this one |
| `PEBBO_TIMEZONE` | `Europe/Zurich` | Time zone for reminders |
| `PEBBO_DECISION_MODEL` | same as `PEBBO_LLM_MODEL` | Ollama model of the action agent that picks tools after every sentence |
| `PEBBO_QUIET_HOURS` | `22:00-07:00` | Quiet hours: routines do not speak in this window |
| `PEBBO_PRESENCE_AWAY_MINUTES` | `60` | Minutes without hearing a person after which they count as away, for "when I leave" routines |
| `PEBBO_LATITUDE`, `PEBBO_LONGITUDE` | none | Location for sunrise and sunset routines, computed locally |
| `PEBBO_LOG_TRANSCRIPTS` | off | Set to `1` to log what was said at `INFO`, for troubleshooting only |
| `PEBBO_LOG_LEVEL` | `INFO` | `INFO` logs who was recognised (as a person number and similarity), new voice requests and chosen actions, never what was said. `DEBUG` also logs transcripts and timings for troubleshooting. Do not share such logs, they contain what was said. |

## Testing without a microphone

`core/tools/e2e_voice.py` plays a script of WAV clips into a running core over WebRTC, prints what Pebbo heard, said and felt, and records its reply:

```sh
uv run python tools/e2e_voice.py script.json --out reply.wav
```

A script is a JSON list of steps such as `{"at": 7, "clip": "hey-pebbo.wav"}` and a final `{"at": 45, "end": true}`.

## Measured on the reference PC

| Step | Time |
| --- | --- |
| Speech recognition of a 4-second sentence (Whisper large-v3-turbo, GPU, greedy decoding) | about 0.4 s |
| First token of the language model (Ministral 3 8B, GPU) | about 0.1 s |
| First audio of speech synthesis (Pocket TTS, CPU) | about 0.2 to 0.3 s |
| End of the user's sentence to Pebbo's first word, end to end | about 2 to 2.7 s |

The phase 1 target is under 1.5 seconds. The largest remaining delays are waiting for silence before transcribing, the end-of-turn decision and synthesising a complete first sentence.
