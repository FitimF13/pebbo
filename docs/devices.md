# Pebbo bodies

A body is the physical Pebbo on the desk: an ESP32-S3-BOX-3 in the printed case (see [hardware](../hardware/README.md)). It streams sound from its microphones to the Pebbo core on the home network and plays Pebbo's voice, face and lights. Speech recognition, the language model, memory and everything else run in the core, exactly as for the PC app.

## What runs Pebbo

The core needs a computer with an NVIDIA GPU with 8 GB of memory, see [running Pebbo](running.md#requirements). It has to be on whenever Pebbo should listen.

| Stage | Computer | Cost (CHF, November 2026) | Notes |
| --- | --- | --- | --- |
| Now | The existing gaming laptop | 0 | Works today. Set the laptop's battery charge limit to 60 to 80 percent when it stays plugged in. It draws an estimated 20 to 40 W while idle with the models loaded. |
| Always on, no code changes | A used PC with an NVIDIA RTX 3060 12 GB (Ricardo, Tutti) | about 600 | Same software, more GPU memory, faster answers. An estimated 35 to 60 W idle. |
| Always on, lowest running cost | Mac mini M4 or M6 with 16 GB | 600 (used) to 780 (new) | About 3 W idle. Needs a Metal speech recognition backend in the core first (mlx-whisper), which Pebbo does not have yet. |

An N100 mini PC is too slow for the language model and speech recognition. It only makes sense later as the always-on core with a GPU computer as a worker.

## Set up a body

1. **Let bodies reach the core.** Start the core so it listens on the home network:
   `PEBBO_HOST=0.0.0.0 uv run pebbo serve` (PowerShell: `$env:PEBBO_HOST = "0.0.0.0"`). Windows asks once whether Python may accept connections: allow it for private networks only. Bodies can then reach the core, but the control centre and the PC app still answer only on this computer.
2. **Build the firmware** with the core's address, in an ESP-IDF 6.1 terminal:
   `python hardware/firmware/build_firmware.py --core http://<address of the PC>:8100`.
   The image is written to `hardware/firmware/out/pebbo-box-3.bin`. Give the PC a fixed address in the router, so the body always finds it.
3. **Flash it** with the BOX-3 connected by USB, from the same terminal:
   ```sh
   python -m esptool --chip esp32s3 erase_flash
   python -m esptool --chip esp32s3 write_flash 0x0 hardware/firmware/out/pebbo-box-3.bin
   ```
   Erasing first removes old settings. That matters if the BOX-3 ran the stock xiaozhi firmware: with old settings left over it could fall back to the manufacturer's cloud.
4. **Wi-Fi.** On first start the body opens a hotspot named `Xiaozhi-XXXX`. Join it with a phone, open `http://192.168.4.1` and enter the home Wi-Fi. Under "Advanced", the OTA address can be changed later without rebuilding the firmware.
5. **Pair it.** The body shows and says a six-digit code. Open the control centre, tab **Geräte**, and enter the code. The body connects and Pebbo greets you. A removed body must pair again.
6. **Talk.** Say "Hey Pebbo" as with the PC app. Pressing the cap mutes the microphones. A click on the BOX-3's boot button (left side, under the case) pauses and resumes listening.

## How it works

The body runs the open-source [xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) firmware (MIT) with Pebbo's own board code ([hardware/firmware/](../hardware/firmware/)). Pebbo's core speaks the firmware's protocol itself, so the body never contacts the manufacturer's servers:

| Step | Endpoint | What happens |
| --- | --- | --- |
| Boot | `POST /xiaozhi/ota/` | An unpaired body gets a pairing code (valid for ten minutes). A paired body gets the WebSocket address, its own token and the time. |
| Pairing | `POST /xiaozhi/ota/activate` | The body asks every few seconds whether the code was entered. |
| Conversation | `WS /xiaozhi/v1/` | 16 kHz Opus from the microphones, 24 kHz Opus to the speaker, 60 ms packets. Face changes are sent as emotion messages. |

- **Listening:** the BOX-3 cancels Pebbo's own voice on the device (acoustic echo cancellation), so its microphone stream stays clean while Pebbo speaks and Pebbo can be interrupted. Pebbo's board code keeps the conversation channel open all the time. The core decides when it hears "Hey Pebbo", as for the PC app, so the body has no wake word of its own.
- **Security:** each body has its own token. The core accepts body connections only from private network addresses, and the control centre only from the computer itself (decision 55).
- **Testing without hardware:** `core/tools/device_sim.py` behaves like a body: it pairs, connects, streams WAV clips as Opus and records Pebbo's answers.

```sh
cd core
uv run python tools/device_sim.py script.json --pair --out reply.wav
```
