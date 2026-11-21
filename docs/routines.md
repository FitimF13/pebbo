# Routines, calendar and the morning briefing

Pebbo learns new behaviour by talking. There are no command words: after every sentence the action agent (decision 50) reads the conversation and picks tools by their descriptions. Routines, appointments and the briefing are such tools. This page explains how they behave, how they are stored and how integrations plug into them. The [features](features.md#routines-taught-in-plain-language) describe the goals.

## Teaching a routine

1. **Say it in your own words.** For example:
   - "Pebbo, jeden Werktag um sieben sagst du mir guten Morgen." (every weekday at seven, say good morning)
   - "Wenn ich gehe und niemand mehr da ist, schalte alle Lichter aus und sag mir Bescheid." (when I leave and nobody is home, switch off all lights and tell me)
   - "Wenn Sara heimkommt, erinnere mich daran, die Post zu holen." (when Sara comes home, remind me to get the mail)
   - "Eine Viertelstunde vor Sonnenuntergang sag: Zeit, die Pflanzen zu giessen." (a quarter of an hour before sunset, say: time to water the plants)
2. **Pebbo reads it back** and asks: "Ich habe verstanden: Montag bis Freitag um 07:00 sage ich «Guten Morgen». Soll ich die Routine so speichern?" Until you answer, the routine is a draft and does nothing.
3. **Correct it** by just saying what is different ("Nein, um acht"). The new version replaces the open draft and is read back again.
4. **Say yes** ("Ja, passt") and it is saved. Saying "Nein, lass das" discards it.
5. **Try it:** "Probier es jetzt" checks the conditions now and says what the routine would do, without doing it. The dry run appears in the run log.

Later you can ask "Welche Routinen habe ich?", "Pausier die Lichter-Routine", "Mach sie wieder an" or "Lösch die Morgen-Routine". The owner can manage every routine, everyone else their own.

When a new routine starts on the same trigger as an active one, Pebbo says so while reading it back, so you can decide whether both should apply.

## Safety rules

- **Two steps.** The action agent passes the person's words to `teach_routine`. A second call to the model fills in the routine format; a correction such as "lieber um halb acht" changes the open draft and keeps the rest. On the reference PC this takes 2 to 4 seconds and filled in all five test sentences correctly, including a correction and a smart home action.
- **Smart home actions:** the second call also gets the device list of the integrations (see [smart home](smart-home.md#how-pebbo-uses-it)) and is told to give a tool only a device name or a room. Arguments the tool does not know are dropped and a single value is wrapped where the tool expects a list, because Home Assistant rejects, for example, `domain: "light"` when the routine runs. The read-back always ends in a verb ("werde ich Küchenlicht anschalten").
- **Nothing runs without a yes.** `teach_routine` only creates a draft. `confirm_routine` activates it after the person agreed.
- **Owner approval:** a routine that watches another person (for example "when Sara comes home"), that the agent marks as affecting others, doors, locks or alarms, or that uses a tool only the owner may use, needs the owner. Taught by someone else, it waits as "Wartet auf Freigabe" until the owner approves it in the control centre (tab Routinen, Freigeben). Taught by the owner, the owner's yes is the approval.
- **Permissions at run time:** tool actions run with the permissions of the approving owner, otherwise of the person who taught the routine. The tool registry checks them on every run, so a child's routine cannot call an owner-only tool.
- **Cooldown and daily limit:** every routine has a minimum gap between runs (15 minutes by default) and a maximum number of runs per day (6 by default). The agent can set other values when the person names them.
- **Quiet hours:** routines do not speak during quiet hours (`PEBBO_QUIET_HOURS`, 22:00 to 07:00 by default). Other actions still run, and the run log notes "quiet hours".
- **No language model needed:** the routine scheduler checks triggers and conditions and runs actions on its own. Only teaching needs the model.
- **Run log:** every run, skipped run and dry run is logged with its trigger, each checked condition and each action with its outcome. The last 200 runs per routine are kept.

## What a routine can contain

Pebbo stores routines in its own JSON format. The action agent fills it in; the core checks and normalises it (`pebbo.routines.model`).

| Part | Type | Fields | Example sentence |
| --- | --- | --- | --- |
| Trigger | `time` | `at` (HH:MM), `weekdays` (empty means every day) | "jeden Werktag um sieben" |
| Trigger | `sunrise`, `sunset` | `offset_minutes`, `weekdays` | "eine Viertelstunde vor Sonnenuntergang" |
| Trigger | `arrive`, `leave` | `who`: a person, `anyone`, `first` (arrive) or `last` (leave) | "wenn die letzte Person geht" |
| Trigger | `device` | `entity`, optional `to` | "wenn die Haustür aufgeht" |
| Condition | `weekday` | `days` | "nur am Wochenende" |
| Condition | `time_window` | `from`, `to` (may run past midnight) | "zwischen sechs und elf am Abend" |
| Condition | `quiet_hours`, `outside_quiet_hours` | | "aber nicht in der Nacht" |
| Condition | `person_home`, `person_away` | `who` | "wenn Sara da ist" |
| Condition | `nobody_home`, `someone_home` | | "wenn niemand mehr da ist" |
| Condition | `device_state` | `entity`, `state` | "wenn das Licht im Flur an ist" |
| Action | `say` | `text` | "sag mir guten Morgen" |
| Action | `remind` | `text`, `in_minutes` | "erinnere mich an die Post" |
| Action | `tool` | `tool`, `arguments` | any registered tool, for example a smart home tool |

Routines cannot call the routine tools themselves. Sunrise and sunset are computed locally (NOAA approximation) from `PEBBO_LATITUDE` and `PEBBO_LONGITUDE`; without them Pebbo explains that the location is missing. Optional `report: true` makes Pebbo say the results of its tool actions after a run ("Ich habe drei Lichter ausgeschaltet").

## Presence

Presence is local and, for now, comes only from the voice: when speaker identification recognises a person, they are "near Pebbo" and count as at home. After `PEBBO_PRESENCE_AWAY_MINUTES` (60 by default) without hearing them, they count as away. Arriving and leaving are events for `arrive` and `leave` triggers. Presence lives in memory, so after a restart everyone is unknown until Pebbo hears them again.

Phones on the home Wi-Fi, the phone app connection and a manual "I'm away" switch come with phase 4. Until then, "when I leave" means "when Pebbo has not heard me for a while", so such routines fire about an hour after the last sentence.

## Device states for integrations

The engine reads device states through a small protocol, `pebbo.routines.StateSource`:

```python
class StateSource(Protocol):
    async def get_state(self, entity: str) -> str | None: ...
    def subscribe(self, listener: Callable[[StateChange], None]) -> None: ...
```

A connector, such as the Home Assistant integration, registers itself once with `app.state.routines.add_state_source(source)` and calls the listener with a `StateChange(entity, old, new)` whenever a device changes. Smart home actions are ordinary tools in the registry and become available to routines as soon as they are registered.

## Calendar

- **Local calendar:** appointments for a person or for the whole household, in Pebbo's own database. "Trag mir morgen um neun den Zahnarzt ein" adds one, "Was habe ich morgen?" reads a day, "Sag den Zahnarzt ab" deletes one. In the control centre (tab Kalender) appointments can be listed, added and deleted.
- **Subscriptions (read-only):** the owner adds an ICS address in the control centre. Pebbo reads it every 30 minutes and on "Abgleichen". The events belong to the chosen person or the household. Pebbo's own small parser reads `VEVENT` entries with `DTSTART`, `DTEND` or `DURATION`, `SUMMARY`, `RRULE` (daily, weekly with `BYDAY`, monthly, yearly with `INTERVAL`, `COUNT`, `UNTIL`) and `EXDATE`.
- **Network rules:** Pebbo contacts only the host in the address. A host on the home network (a private IP address, a name without a dot or ending in `.local`, `.lan`, `.home.arpa`, `.internal`) is read directly. Any other host is off until the owner switches on "Externen Host erlauben" for that subscription; then only that host is added to the runtime network guard, only over HTTPS. Switching it off or removing the subscription withdraws the host again. Redirects to other hosts are blocked by the guard, and system proxies are not used. There is no list of fixed hosts: each one is entered and allowed by the owner and shown in the control centre.
- **Privacy:** the control centre shows only the host of a subscription, never the full address, because private calendar links contain a secret. The address is stored in the local database. Today's appointments of the recognised person and of the household are part of Pebbo's context, never for guests.

## Morning briefing

The first time Pebbo recognises a person on a day, from 05:00, and there is something on that day, its context tells the conversation model to offer a short overview at the end of its answer. If the person wants it, the action agent picks `daily_briefing`, which says the day's appointments, open reminders and the routines that still run today at a fixed time, for example: "Guten Morgen, Alex! Heute hast du 2 Termine: ganztägig Ferien und um 09:00 Zahnarzt. Erinnerungen: um 12:00 Paket mitnehmen. Routinen: um 10:00 «Lüften»." Asking "Was steht heute an?" works at any time. Weather is not part of the briefing until an owner-enabled source exists.

## Open points

- Presence from phones, the phone app and Bluetooth beacons (phase 4).
- Triggers for calendar events ("when a meeting starts") and actions that send a push or ask the other instance.
- Calendar connectors with sign-in (iCloud, Google, Microsoft 365) and phones subscribing to Pebbo's calendar (Radicale, decision 27).
- Encrypting stored subscription addresses together with other credentials.
