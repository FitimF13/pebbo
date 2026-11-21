# Release notes

## 0.1.0 (first public release, in preparation)

Pebbo is a local-first desk companion that talks German, remembers each person in the household and acts through tools it picks from the conversation. Nothing leaves the home network unless the owner turns a feature on.

### Talk

- "Hey Pebbo" or "Pebbo" wakes it. After that the conversation flows without the wake word until Pebbo says goodbye or it goes quiet.
- Speech recognition with Whisper large-v3-turbo on an NVIDIA GPU (Whisper `small` on the CPU without one), answers from Ministral 3 8B through Ollama, a German voice from Pocket TTS.
- Pebbo decides on actions while it answers, so a plain sentence is spoken about one second after you stop talking.
- Interruptions work, "mhm" and "ja" do not stop Pebbo, "stopp" does.

### Remember

- Memories per person, told apart by voice (CAM++), with guest mode for unknown voices.
- Reminders in natural language ("in zwei Minuten", "morgen um acht"), spoken at the desk.
- Pebbo never claims to have done something it has not done: spoken confirmations come from the tools that ran.

### Act

- Smart home and music through Home Assistant's MCP server (and Music Assistant inside it): Pebbo uses its tools like its own and knows the state of the devices. Any MCP server can be added in the control centre. See [smart home and music](smart-home.md).
- Routines taught in plain language ("Wenn ich gehe und niemand mehr da ist, schalte alle Lichter aus"), read back and saved only after a yes. They run in the core, even without a language model.
- A calendar per person with read-only ICS subscriptions, and a short morning overview when Pebbo first hears you on a day. See [routines, calendar and briefing](routines.md).

### Body

- A Pebbo body built from an ESP32-S3-BOX-3 with open xiaozhi-esp32 firmware and Pebbo's board code, a printable case with glowing wings, and a shopping list. See [hardware](../hardware/README.md) and [Pebbo bodies](devices.md).

### Phone

- A native iOS and Android app (Expo): pair it with a code or the QR code from the control centre, chat with Pebbo by text with the same personality and tools, and see your reminders and memories. Due reminders show up while the app is open. See [phone app](phone.md).

### More than one computer

- A second instance for the office with its own data. Handoffs between the two instances need an approval. See [office](office.md).
- Compute devices: Pebbo thinks on the best reachable computer and falls back to the always-on box. See [compute](compute.md).

### Security and privacy

- A network guard blocks every outbound connection in tests. Third-party software is audited for telemetry, see [third-party software](third-party.md).
- The control centre answers only on this computer and refuses requests from foreign web pages. Bodies, phones and instances pair with single-use codes; guessing a code withdraws it. On Windows the network guard also covers asyncio connections.

### Known limits

- The body firmware and case are not yet verified on a printed and assembled unit.
- The iOS app store submission follows later. The phone app works only on the home network and has no push notifications yet.
- Home Assistant, the routines and ICS subscriptions are tested against local fakes only, not yet against a real Home Assistant or a real calendar feed. Device-state triggers for routines are not yet connected to Home Assistant.
