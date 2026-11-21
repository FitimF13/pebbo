# Smart home and music

Pebbo controls the home through [Home Assistant](https://www.home-assistant.io) and plays music through [Music Assistant](https://music-assistant.io), which Home Assistant integrates. Both talk to Pebbo through the Model Context Protocol (MCP): Home Assistant has a built-in MCP server, and Pebbo uses every tool it offers like one of its own tools. There are no command words. After every sentence, Pebbo's action agent reads the conversation and the tools' descriptions and decides whether one of them fits, for example "Mach das Licht im Wohnzimmer an" or "Pause die Musik".

Everything stays in the home network: Pebbo connects only to MCP servers on private or loopback addresses unless the owner explicitly allows a public address for a server.

Menu names are given in English with the German Home Assistant labels in brackets. They can differ slightly between Home Assistant versions.

## 1. Enable Home Assistant's MCP server

1. In Home Assistant open **Settings > Devices & services** (Einstellungen > Geräte & Dienste) and choose **Add integration** (Integration hinzufügen).
2. Search for **Model Context Protocol Server** and add it.
3. The server is reachable at `http://<home-assistant>:8123/api/mcp`. Pebbo should use the device control set at `http://<home-assistant>:8123/api/mcp/assist`: it contains only the devices exposed to Assist. The full **Home Assistant** set is meant for administrators and can reach every entity, so do not give it to Pebbo.

## 2. Choose which devices Pebbo may use

Pebbo can use exactly the entities that are exposed to Assist.

1. Open **Settings > Voice assistants** (Einstellungen > Sprachassistenten).
2. On the Assist card, select the line with the number of exposed entities (for example "12 entities exposed") to open the **Expose** tab (Freigeben).
3. Choose **Expose entities** (Entitäten freigeben), select the lights, switches, covers and media players Pebbo may use, and confirm.
4. Turn off **Expose new entities** if new devices should not appear in Pebbo automatically.

Do not expose locks, alarms or garage doors unless every household member may use them by voice: voice identifies people, it does not authenticate them. Approvals for risky device actions are planned, see [features](features.md#smart-home).

## 3. Create an access token

Pebbo signs in with a long-lived access token.

1. Ideally create a separate Home Assistant user for Pebbo under **Settings > People > Users** (Einstellungen > Personen > Benutzer), so the token can be revoked on its own.
2. Signed in as that user, open your **profile** (bottom left), tab **Security** (Sicherheit).
3. Under **Long-lived access tokens** (Langlebige Zugangstoken) choose **Create token** (Token erstellen), name it "Pebbo" and copy it. Home Assistant shows it only once.

The MCP server's option **Require an administrator account** is on by default. If Pebbo reports that the server refused the token, either use a token of an administrator or switch this option off in the integration's settings.

## 4. Add it in Pebbo

1. Open Pebbo's control centre, tab **Integrationen**.
2. Enter a name (for example "Home Assistant"), the address from step 1 (for example `http://192.168.1.20:8123/api/mcp/assist`) and the token from step 3.
3. Choose who may use it:
   - **Haushalt** (default): recognised household members.
   - **Nur Besitzer**: only the owner.
   - **Alle, auch Gäste**: also unknown voices, for example for music. Device states are still never told to guests.
4. Choose **Hinzufügen**. Pebbo connects, lists the tools and shows **Verbunden** with the number of tools. A server that cannot be reached or refuses the token shows the reason instead, and the conversation goes on without its tools.

The token is stored only in Pebbo's local database. The control centre can replace it with **Token ändern** but never shows it again. **Neu verbinden** lists the tools again, for example after exposing more devices in Home Assistant. Pebbo also reconnects to all servers when it starts.

## How Pebbo uses it

- **Actions:** each Home Assistant tool appears to Pebbo as `<name>_<tool>`, for example `home_assistant_HassTurnOn`, with Home Assistant's description and parameters. When the action agent picks one, the registry checks the permission, Pebbo calls the tool and says Home Assistant's short answer, or "Erledigt." when there is none, right after its own answer. A failed call is "Das hat nicht geklappt."
- **Device states:** if the server offers Home Assistant's `GetLiveContext` tool, Pebbo does not offer it as an action. Instead, for a recognised household member, it adds a compact list of the exposed devices and their states to the conversation context (refreshed at most every 30 seconds, after every device action, and cut to about 1200 characters). That lets Pebbo answer "Ist das Licht im Wohnzimmer an?" truthfully. Guests never get this list.
- **Not used:** `GetDateTime`, because Pebbo knows the time itself.

## Music through Music Assistant

Music Assistant connects music services such as Spotify and YouTube Music to speakers such as Sonos, Chromecast, AirPlay and Bluetooth boxes. It needs its own Music Assistant server (version 2.4 or newer). On Home Assistant OS the integration can install it as an app.

1. Install the Music Assistant server and add your music providers and speakers there.
2. In Home Assistant add the **Music Assistant** integration (Settings > Devices & services > Add integration). Every Music Assistant player and group becomes a media player entity in Home Assistant.
3. Expose these media players to Assist (step 2 above).
4. Click **Neu verbinden** for Home Assistant in Pebbo's control centre.

Pebbo then uses Home Assistant's media tools for the exposed players, such as pausing, resuming, skipping and the volume, and, where Home Assistant offers it for the player, searching and playing music ("Spiel etwas Jazz im Wohnzimmer"). Name the players after their rooms in Home Assistant, so "im Wohnzimmer" finds the right one.

## Other MCP servers

Any MCP server with Streamable HTTP can be added the same way. Pebbo applies the same rules to it: its tools get the server's permission, its address must be in the home network and its token is never shown again. Check what a server's tools can do before adding it.

### Public addresses

An MCP server outside the home network is refused unless **Öffentliche Adresse erlauben** is ticked for it. Only then does Pebbo add exactly that host to its network guard. The control centre shows every allowed public host next to its server ("Öffentliche Adresse erlaubt: …"), and the host is removed from the guard again when the server is switched off, changed or removed. This is off by default and not needed for Home Assistant at home.

## Troubleshooting

| Shown in the control centre | Meaning |
| --- | --- |
| Nicht erreichbar | Pebbo could not connect. Check the address, the port and that Home Assistant is running. |
| Der Server hat den Zugangstoken abgelehnt. | The token is wrong, revoked, or its user is not an administrator while the server requires one. |
| Diese Adresse liegt nicht im Heimnetz. | The address resolves to a public IP. Use the local address of Home Assistant. |
| Diese Adresse finde ich nicht. | The host name cannot be resolved. Use the IP address instead, for example `192.168.1.20`. |

Pebbo logs tool calls with their arguments only at `DEBUG` and never logs tokens.
