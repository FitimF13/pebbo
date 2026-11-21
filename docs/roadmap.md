# Roadmap

Rule: no hardware is bought until everything runs on the gaming PC. During development, the services that will later live on the always-on box run in containers on the gaming PC. Every phase ends with a demo and its acceptance checks, and the default tests run without network access.

Current state: phases 0 and 1 are done and tested on the reference PC. Phase 2 is ready for testing, see [running Pebbo](running.md). At the owner's request, the body of phase 7 came early (decision 58): the core serves ESP32-S3-BOX-3 bodies, and the case, firmware and shopping list are in [hardware](../hardware/README.md). Pebbo acts through tools it picks from the conversation (decision 50), which phase 3 extends with the smart home, music and calendars. Phase 3 has started: Home Assistant, and Music Assistant through it, connect as MCP servers whose tools Pebbo uses like its own (see [smart home and music](smart-home.md)). Routines taught in plain language, calendars with ICS subscriptions and the morning briefing are in [routines](routines.md). Two instances with approved handoffs (phase 5) are in [office](office.md), compute devices and the fallback for the always-on box (phase 6 software) in [compute](compute.md). From the end of a sentence to the first spoken word takes about 0.7 to 1.6 seconds on the reference PC, against a target of 1.5 seconds. The first web control centre is part of phase 2. Phase 4 has started: phones pair with the core and chat with Pebbo, see their reminders and memories on the home network (see [phone app](phone.md)). Push notifications, the push gateway, the relay for use away from home and the App Store release need external accounts and are still open.

## Version 1 and the way there

Version 1 contains every phase below, plus English (decision 90), setup through the owner's agent with `pebbo setup` and `pebbo doctor` including a local Home Assistant (decisions 85 and 86), and a phone app built from native components (decision 91). Until then the repository is public as an alpha (decision 94).

Next steps, in order:

1. Agents test the whole software end to end on the reference PC and fix what they find.
2. The owner tests in short sessions of about 15 minutes, one area each: conversation and memory on the PC, reminders with the phone app, the smart home with real devices. Findings become issues.
3. When the software sessions pass, the body follows: an ESP32-S3-BOX-3 in a case from a print service. The always-on box follows at the gate.

| Phase | Goal | Acceptance checks |
| --- | --- | --- |
| 0. Foundation | Repository structure, licence files, contribution guide, continuous integration, decision records | CI runs type checks and tests. A network guard fails any test that opens an outbound connection. |
| 1. Talk | Natural spoken conversation on the PC: "Hey Pebbo", streaming German speech recognition, local model on the GPU, German voice, interruptions and backchannels, face with basic states and lip sync | A ten-minute conversation without a single click. Median time from end of speech to first spoken word under 1.5 seconds (target to be confirmed by measurement). "Mhm" and "ja" do not stop Pebbo, "stopp" does. A network monitor shows no connection leaving the PC. |
| 2. Remember | Memory per person, conversation summaries, gradual voice onboarding and guest mode, requested reminders spoken at the desk | Two test voices are told apart. A fact survives a restart. A guest gets no personal answers. "Erinnere mich in zwei Minuten" is spoken on time. |
| 3. Act | Home Assistant in a container, routines taught in plain language, music through Music Assistant on all three targets, calendars | A taught routine ("when I leave, turn off the lights") runs in a simulated scenario. A playlist starts on the chosen target. Today's appointments appear in a briefing. |
| 4. Reach | Native phone apps for iOS and Android (Expo) with encrypted push and the push gateway, presence-based delivery, VPS relay, compute devices and providers in the settings, proactive behaviour | A reminder reaches the phone when the person is away and is spoken when they are near. The app works away from home through the relay. A compute device can be paired and removed. |
| 5. Two Pebbos | A second instance for the office with its own data, end-of-day handoff with approval | The office instance cannot read home data. An approved handoff arrives at home, a rejected one does not. |
| **Gate** | **Everything above runs on the gaming PC** | **Decide together whether to buy hardware.** |
| 6. Always-on box | Buy the N100-class box, benchmark the fallback model and German speech recognition, move the core and Home Assistant | Pebbo keeps working with the gaming PC switched off, with reduced answer quality. |
| 7. Body | Choose and measure display, microphones, speaker, LED ring and touch sensor. Device firmware, case design fitted to the real parts, printing through a print service, assembly guide | One assembled Pebbo on the desk works like the PC version. Bill of materials, CAD sources and print settings are in the repository. |
| 8. Open source release | Documentation polish, licence check of every dependency, model and voice, security review, App Store submission of the iOS app with a demo mode for the review | Public repository with release notes. The iOS app is available in the App Store. Android build instructions work from a clean checkout. |

## Open questions

1. Which concrete always-on box (an N100 mini PC or a Raspberry Pi 5), after benchmarking the fallback model and German speech recognition?
2. Which German speech synthesis model sounds best under a permissive licence? See [research](research.md).
