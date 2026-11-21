# Features

This document describes what Pebbo does and the rules each capability follows. The [architecture](architecture.md) describes how it is built. Examples use German phrases where they matter for speech, with English translations.

## Conversation

- **Wake word:** "Hey Pebbo" starts a conversation. A visible and physical mute always wins over everything else.
- **Hands-free:** after the wake word, the person speaks and Pebbo answers out loud. Follow-up turns need no repeated wake word while the conversation is active.
- **Streaming:** Pebbo starts speaking after its first sentence is ready instead of waiting for the full answer.
- **Language:** standard German and English (decision 90). Swiss German is a later goal.
- **Talking to the right person:** Pebbo addresses the recognised person as "du" and answers questions about themselves from what it knows: "Wie trinke ich meinen Kaffee?" (how do I take my coffee?) gets "Ohne Zucker!", "Weisst du, wer ich bin?" gets "Du bist Sara!". A guest who asks about someone else hears that Pebbo does not talk about others (decision 99).
- **Only what is meant to be heard:** emojis, markdown, emotion tags and stage notes in parentheses, square brackets or asterisks are never spoken, even when a note spans several sentences. Sentences that claim an action Pebbo did not carry out, promise to pass something on to someone, or have the robot eat or drink are dropped. The app chat cleans its answers the same way.

### Interruptions and backchannels

Pebbo keeps listening while it speaks and distinguishes:

| The person says | Pebbo |
| --- | --- |
| A backchannel such as "mhm", "ja", "genau" (yes, exactly) | Keeps talking |
| A stop word or a real correction such as "stopp" or "nein, morgen" (no, tomorrow) | Stops at once and listens |
| Only "warte mal" or "Moment" (hold on) | Stops and listens without answering |
| Something while music plays | Lowers the music when it hears the wake word |

## Memory

- **Facts and preferences:** "Der Ersatzschlüssel liegt in der Schublade" (the spare key is in the drawer). Pebbo may suggest saving something it heard, and saves it for the person it belongs to.
- **Conversation summaries:** short summaries of past conversations so Pebbo knows what was discussed yesterday. Raw audio is never stored.
- **Plans and lists:** training and meal plans, shopping lists, tasks and appointments.
- **Control:** every memory shows its origin and can be viewed, edited and deleted in the app. "Vergiss das" (forget that) removes the last memory.

## Reminders and delivery

A person can ask Pebbo to become active later: "Hey Pebbo, erinnere mich morgen früh, das Paket mitzunehmen" (remind me tomorrow morning to take the parcel). Pebbo confirms the exact time ("Morgen um 7:30?") and acts on its own at that moment. Vague times such as "tomorrow morning" map to a per-person default.

When the reminder is due, Pebbo picks the delivery:

| Situation | Delivery |
| --- | --- |
| The person is home and was recently heard near Pebbo | Spoken out loud. Without an acknowledgement ("ok", "danke") within a few minutes, it also goes to the phone. |
| The person is home but not near Pebbo | Push to the phone, optionally also spoken |
| The person is away | Push only. Pebbo stays silent at home so it does not announce private things to others. |
| Presence unknown | Push to the phone |
| Quiet hours | Push only, unless the reminder is marked urgent |

### Presence detection

All signals are local. Pebbo never tracks GPS location.

- **Voice near Pebbo:** recent speech recognised as that person. Strongest signal. This is the only signal implemented so far (see [presence](routines.md#presence)).
- **Phone on the home Wi-Fi:** the person's phone is seen on the local network. Phones may sleep, so this is combined with other signals.
- **Phone app connection:** whether the app is connected through the home network or through the relay.
- **Optional:** Bluetooth presence beacons, or a manual "I'm away" switch in the app.

Each person sees and can change their delivery rules in the app.

## Proactive behaviour

- **Reminders:** spoken or pushed as described above.
- **Morning briefing:** when Pebbo first hears someone in the morning, it offers the day's reminders, plans and appointments. Weather only from a source the owner has enabled. Implemented for appointments, reminders and routines, see [morning briefing](routines.md#morning-briefing).
- **Small talk and tips:** occasionally a short conversation or a fitting tip, for example about a plan or something it remembered.

Rules so Pebbo stays charming:

- It speaks up only when someone is nearby, never during quiet hours, calls, music someone is listening to, or while another person is talking.
- Unprompted small talk has a daily limit and a cooldown, adjustable per person, with an easy "nicht jetzt" (not now).
- Personal topics go only to the person they belong to. With guests present, Pebbo stays general.

## Routines taught in plain language

Every person can teach Pebbo new behaviour: "Pebbo, wenn ich die Wohnung verlasse und niemand mehr zu Hause ist, schau, ob alle Lichter aus sind" (when I leave the flat and nobody else is home, check that all lights are off).

1. **Understand:** Pebbo turns the sentence into a routine with a trigger, conditions and actions.
2. **Confirm:** it reads the routine back in its own words and asks about open details ("All lights, or only living room and kitchen? Should I tell you when I did it?"). Nothing is saved without a yes.
3. **Save:** the routine belongs to the person who taught it and appears in the app, where it can be edited, paused, tested or deleted.
4. **Run:** when the trigger fires, Pebbo checks the conditions, acts and reports in the agreed way, for example a push "Ich habe drei Lichter ausgeschaltet" (I turned off three lights).

| Part | Examples |
| --- | --- |
| Triggers | Someone leaves or arrives, the last person leaves, a time, sunrise or sunset, a device changes state, a calendar event starts |
| Conditions | Nobody home, a specific person home, weekday, quiet hours, a device state |
| Actions | Switch devices or scenes, play music, remind someone, send a push, ask the other instance to run a routine after approval |

Safety rules:

- Routines keep working when no language model is available.
- Routines affecting shared devices are visible to the whole household. Routines that unlock doors, disable alarms or affect someone else need the owner's approval.
- Pebbo points out contradicting routines while teaching and asks which one wins.
- "Probier es jetzt" (try it now) runs a routine once, or shows what it would do without acting.
- Every run is logged with its trigger, the checked conditions and the actions taken.
- Each routine has a cooldown and a daily limit.

Current state: teaching, confirming, pausing, trying and the run log work as described, see [routines](routines.md). Triggers are a time, sunrise or sunset, someone arriving or leaving (from voice presence only for now), and device changes reported by an integration. Calendar event triggers, push actions and requests to the other instance are still open. Pebbo points out an active routine with the same trigger while teaching. The control centre can pause, resume, approve, test and delete routines; editing a saved routine there is still open.

## People, voices and guests

Pebbo learns voices gradually in everyday use. Only the owner adds people.

1. The owner invites a person in the app with a name, a role (adult, child, colleague) and permissions. The person accepts on their own phone and agrees to voice recognition.
2. When Pebbo hears an unknown voice, it asks casually who it is. If the answer matches an invited person, that person confirms once in their app, so nobody can simply claim to be someone else.
3. From then on, Pebbo collects voice samples whenever it is confident who is speaking. Until it is confident enough, it asks briefly ("Sara, bist du das?") before sharing anything personal.

**Guest mode** applies to unknown or uncertain voices: general questions, timers, music and jokes work. Personal memories, reminders, calendars and devices that need approval do not.

**Several voices in one conversation:** a short, unclear sentence keeps the person Pebbo recognised before, but a voice that clearly sounds different is treated as a guest at once. When someone else starts speaking, what the person before said is summarised for them and removed from the conversation, so the guest never hears it, not even from the language model's memory of the last minutes (decision 98). Only a self-introduction ("Ich bin Sara", "Sara hier") claims a voice; a guest who talks about Sara does not.

**Privacy:** Pebbo stores a voice fingerprint (a numeric embedding) per person, never recordings. Each person can pause recognition or delete their profile. Voice recognition identifies, it does not authenticate: sensitive actions always need a confirmation in the app.

## Smart home

- Pebbo controls devices through a local, open-source smart home hub (Home Assistant). It never needs a vendor cloud.
- Home Assistant is connected through its built-in MCP server. Its tools are Pebbo's tools: the action agent picks them from the conversation, without command words. See [smart home and music](smart-home.md).
- The owner chooses which devices and actions Pebbo may use: in Home Assistant by exposing devices to Assist, and in the control centre by choosing who may use the integration (everyone, household or owner only).
- Pebbo knows the current state of the exposed devices for recognised household members, so it answers "Ist das Licht an?" truthfully. Guests never get device states.
- Risky actions need approval. *Planned:* approvals per device or tool; until then, risky devices such as locks should not be exposed to Assist.

## Music

- Music runs through Music Assistant, whose players appear as media players in Home Assistant and are controlled through Home Assistant's MCP server.
- Spotify and YouTube Music, each person with their own account.
- Playback targets: a Bluetooth box, Pebbo's own speaker, or network speakers (Sonos, Chromecast, AirPlay).
- Each person sets a default target and room names ("spiel meine Playlist im Wohnzimmer", play my playlist in the living room).

## Calendars

- **Pebbo's own calendar:** local, phones can subscribe to it.
- **Connectors:** iCloud, Google Calendar and Microsoft 365. Each is an external service that the person enables explicitly.
- **Read-only first:** appointments feed briefings, reminders and conflict hints. Creating appointments in external calendars comes later and needs approval each time.
- **Separated:** the office Pebbo uses the work calendar, the home Pebbo the private ones. Credentials stay encrypted on the home box.

Current state: Pebbo's own calendar lives in its database, with appointments per person or for the household, added by voice or in the control centre. Any calendar that offers an ICS address (iCloud, Google and Microsoft 365 all do) can be subscribed read-only; a host outside the home network needs the owner's permission. Today's appointments are part of the recognised person's context. See [routines, calendar and the morning briefing](routines.md#calendar).

## Home and office

- Each instance has its own people, data, devices and credentials. Neither can read the other's data.
- The office Pebbo has every home feature, plus:
  - **End-of-day handoff:** at closing time it suggests a summary of open tasks and follow-ups and sends it to the home Pebbo after approval.
  - **Work appointments and tasks** with reminders.
  - **PC tasks:** opening allowlisted applications and summarising selected documents, each time with approval on the PC.
- Every exchange between instances shows the exact content and destination, needs a one-time approval and is logged.

## Phone app

- **Native apps for iOS and Android**, built with React Native and Expo, as native as possible: native navigation and gestures, SF Symbols on iOS, haptics, smooth streaming chat, widgets and quick actions later.
- **Look:** Pebbo's character (its face, the cream, lavender and warm glow palette from the concept, playful details) combined with the clean, modern feel of current apps such as the ChatGPT and T3 Code mobile apps. Light and dark mode.
- **Content:** chat with Pebbo (text and voice), reminders, memories, routines, approvals, people and settings, and switching between home and office.
- **Pairing:** the app connects to any self-hosted Pebbo by scanning a QR code shown in the settings. There is no central Pebbo account or server.
- **Status:** the first version pairs on the home network and has the text chat, reminders, memories and settings. Push, the relay and the App Store release are still open. See [phone app](phone.md).
- **Away from home:** works through the relay. Lock-screen notifications use neutral text and the content is end-to-end encrypted.
- **Distribution:**
  - **Self-build for everyone:** anyone can build, sign and install the iOS and Android apps from the repository, with documented steps.
  - **App Store as a convenience:** because the project needs the iOS app itself, it also publishes it in the App Store, so people can simply download it.
  - **Android:** built and installed from the repository. A store release can follow later.
- Optional adapters such as Telegram or ntfy can be added by the community.

## Face, animations and lights

**Style:** as in the concept image. Glowing line eyes and mouth with pink cheeks on a dark screen.

| Group | Examples |
| --- | --- |
| Basic states | Sleeping, waking up, listening, thinking, speaking with lip sync |
| Feelings | Happy, laughing, surprised, sad, embarrassed, a bit sulky, proud |
| Idle life | Random blinking, looking around, yawning, a wink or a hum when nothing happens for a while |
| Touch | Giggles when someone taps its head |

- The mouth moves only while Pebbo speaks and follows its voice.
- The language model adds an emotion tag to each reply. The tag is never spoken.
- Pebbo falls asleep after a while without anyone nearby.

**LED ring and wings** show status (listening, thinking, muted in red, error), mood (colour and pulse) and waiting notifications (a soft glow). Brightness dims at night.

## Control centre

The full control centre runs in the browser and is served by the core. It manages people and voices, memories, reminders, routines, devices, compute devices, providers and integrations. The phone apps contain only the daily essentials and link to the web control centre for everything else.

## Settings: compute devices and providers

Each Pebbo has a settings page where the owner manages where thinking and speech happen:

- **Add a compute device:** install a small Pebbo worker on another machine (for example a gaming PC) and pair it with a short-lived code. The worker reports what it can run and how fast.
- **Remove a compute device:** unpair it. Its access ends immediately.
- **Model providers:** local runtimes and optional external providers. External providers are off by default and clearly marked.
- **Routing rules:** which provider handles quick chat, hard questions and private topics, and the fallback order when a device is offline. Private topics never leave the house unless the owner allows it.
- **Transparency:** for every answer, which device produced it, how long it took and whether anything left the local network.

The same pairing flow is used for phones, Pebbo bodies and the second instance.
