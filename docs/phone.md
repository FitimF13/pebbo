# Phone app

The phone app is the daily companion to Pebbo (decision 42): chat with Pebbo, see and cancel your reminders, see and delete what Pebbo knows about you, and get due reminders while the app is open. It is a native iOS and Android app built with Expo and React Native (decision 29) in [`apps/mobile`](../apps/mobile). Everything else stays in the web control centre.

This is the first part of phase 4 of the [roadmap](roadmap.md). It works on the home network without any external account. Push notifications, the relay for use away from home and the App Store release are still open, see [what is still open](#what-is-still-open).

## Pairing a phone

Every phone belongs to exactly one person. Only the owner pairs phones, in the control centre on the computer that runs Pebbo.

1. Start the core so that it listens on the home network: `PEBBO_HOST=0.0.0.0` (see [running Pebbo](running.md#settings)). The control centre still answers only on this computer.
2. Open the control centre, go to **Geräte**, and under **Handys** choose the person and click **Code erstellen**. Pebbo shows a six-digit code and a QR code. If the computer has several addresses on the network (for example a virtual network of Docker or WSL), pick the one of the home Wi-Fi.
3. On the phone, scan the QR code with the camera app. It opens the Pebbo app with the address and the code filled in. Without a camera, open the app and type the address (for example `192.168.1.20`, the port 8100 is added) and the code.
4. Give the phone a name and tap **Koppeln**. The phone is now listed in the control centre under the person.

How it works:

- The QR code contains a link `pebbo://pair?address=http://192.168.1.20:8100&code=123456`. It is drawn in the browser by [uqr](https://github.com/unjs/uqr). No QR service is contacted.
- The code is valid for ten minutes and only once. Creating a new code for the same person ends the earlier one. After five wrong codes every open code ends, so the six digits cannot be guessed.
- The phone exchanges the code once at `POST /api/app/pair` for its own random token (256 bit). The token is kept in the Keychain on iOS and the Keystore on Android (expo-secure-store, only on this device and not in backups). The core stores only a SHA-256 hash of the token and of the code.
- Every request of the app carries the token. The core looks it up on every request, so **Entkoppeln** in the control centre ends the phone's access at once. Removing a person removes their phones. **Entkoppeln** in the app's settings removes the phone on the core too.
- A phone acts only for its person. It sees only that person's memories and reminders, and Pebbo answers it with that person's context. The person and the permissions are checked by the core, never by the app.

## Using the app

- **Chat:** write to Pebbo. Pebbo answers with the same personality and the same knowledge as when you talk to it, and its face at the top shows its feeling. It acts the same way: "Merk dir, ich trinke Kaffee ohne Zucker" stores a fact, "Erinnere mich morgen um acht ans Paket" plans a reminder, "Vergiss das" removes the last fact. What Pebbo did appears as small confirmations under its answer.
- **Erinnerungen:** your open reminders. Swipe down to refresh, tap the bin to cancel one.
- **Gedächtnis:** what Pebbo knows about you and where it comes from. Tap the bin to delete an entry.
- **Einstellungen:** who this phone belongs to, the Pebbo it talks to, and **Entkoppeln**.
- **Due reminders:** while the app is open, it asks Pebbo every 15 seconds for reminders that became due. They appear at the top of the chat, the phone vibrates, and **Gesehen** acknowledges them. An acknowledged reminder counts as delivered, so Pebbo does not say it out loud later. When the app is closed, reminders are only spoken by Pebbo, because push notifications are not built yet.
- Light and dark mode follow the phone's setting.

The chat thinks on the same compute device as a new voice conversation (see [compute](compute.md)). It keeps the last ten messages per phone in the core's memory, so "das" in "vergiss das" refers to the right thing. They are not stored in the database and are gone when the core restarts. Text chats are not summarised yet.

## App API

All routes are under `/api/app/` and, except pairing, need `Authorization: Bearer <token>`. The types are in [`packages/contracts/src/phone.ts`](../packages/contracts/src/phone.ts), the implementation in [`core/src/pebbo/phones.py`](../core/src/pebbo/phones.py).

| Route | Purpose |
| --- | --- |
| `POST /pair` `{code, name}` | Exchange a pairing code for a token. Returns `{token, phone, person}`. |
| `GET /me` | The phone's person, the phone and the core's version |
| `DELETE /me` | Unpair this phone |
| `GET /reminders`, `DELETE /reminders/{id}` | The person's open reminders, cancel one |
| `GET /memories`, `DELETE /memories/{id}` | The person's memories, delete one |
| `POST /chat` `{text}` | Pebbo's answer `{answer, emotion, actions}`. `actions` are the confirmations of what Pebbo did. |
| `GET /notifications` | Reminders that became due since the phone last acknowledged |
| `POST /notifications/ack` `{until}` | Acknowledge everything due up to `until` (Unix time) |

The control centre manages phones with `GET /api/control/phones`, `POST /api/control/phones/pairings` `{person_id}`, `DELETE /api/control/phones/pairings/{id}` and `DELETE /api/control/phones/{id}`. These routes, like the rest of the control centre, answer only on the computer that runs the core.

### Network access

The core answers `/api/app/` and the body endpoints `/xiaozhi/` from private addresses of the home network (`192.168.x.x`, `10.x.x.x`, `172.16.x.x` to `172.31.x.x`, IPv6 `fc00::/7`). Public addresses and link-local addresses are refused, as are paths with `.` or `..` segments and requests with an `Origin` header, so a web page in a browser cannot speak for a phone. From the computer itself the app API is always reachable, also under another host name such as `10.0.2.2` from the Android emulator. Everything else, the control centre and the PC app included, answers only on the computer itself (`pebbo.access`).

`PEBBO_APP_ADDRESS` overrides the address put into the QR code, for example `http://pebbo.local:8100`.

On the home network the app talks to the core over plain HTTP. The Wi-Fi encryption protects it from outside, but other devices on the same network could read the traffic, including the token. Encrypted connections come with the relay (decision 38). Until then, pair phones only on a home network you trust.

## Building the app

The app is plain Expo with these native modules: expo-secure-store, expo-haptics, expo-status-bar, expo-system-ui, react-native-svg, react-native-screens and react-native-safe-area-context. Always start the Expo CLI through the package scripts. They run `scripts/expo.mjs`, which sets `EXPO_NO_TELEMETRY=1` (no usage data to Expo) and `EXPO_OFFLINE=1` (no requests to Expo's servers).

```sh
pnpm install                              # once, at the repository root
pnpm --filter @pebbo/mobile typecheck
pnpm --filter @pebbo/mobile test          # unit tests of the API client and pairing, offline
pnpm --filter @pebbo/mobile build         # bundles the app for iOS and Android offline into apps/mobile/dist
```

`pnpm build` at the root runs the same offline export. It checks that the app bundles for both platforms. It is not an installable app.

### On a device or simulator

Development builds need Xcode (iOS, on a Mac) or Android Studio (Android). The first build downloads CocoaPods and Gradle dependencies, which needs internet once.

```sh
cd apps/mobile
pnpm ios        # expo run:ios, builds and starts the app in the simulator or on a connected iPhone
pnpm android    # expo run:android, the same for an emulator or a connected Android phone
pnpm start      # only the Metro bundler, for an already installed development build
```

The phone and the computer that runs Metro must be on the same network. Expo Go is not recommended, because it is Expo's own app and talks to Expo's servers.

### Release builds

- **Android:** `npx expo prebuild --platform android`, then `cd android && ./gradlew assembleRelease`. Sign the APK with your own key and install it. The app allows plain HTTP (`usesCleartextTraffic`), because the core on the home network has no TLS yet.
- **iOS:** `npx expo prebuild --platform ios`, open `ios/Pebbo.xcworkspace` in Xcode, choose your team and archive. The app may use plain HTTP only to local addresses (`NSAllowsLocalNetworking`) and asks once for access to the local network.
- **Cloud builds:** decision 29 chose Codemagic. EAS Build works as well. Both need an account and are not set up yet.

### What the app contacts

Only the Pebbo it was paired with. It has no analytics, no crash reporting, no update service (expo-updates is not included) and no in-app camera. The QR code is read by the phone's own camera app, which opens the `pebbo://pair` link. An in-app scanner was left out because expo-camera scans codes on Android with Google ML Kit, which according to Google's terms may contact Google's servers and send usage metrics.

## What is still open

These parts of phase 4 need external accounts or services and are not built yet:

- **Push notifications while the app is closed:** the push gateway for the App Store app, Apple Push Notification service, UnifiedPush or Firebase Cloud Messaging, and the end-to-end encryption of notifications (see [architecture](architecture.md#network-and-outbound-policy)). Until then, due reminders reach the phone only while the app is open.
- **Away from home:** the relay on the VPS (decision 38). The app works only on the home network.
- **App Store release** and signed builds through Codemagic (decision 29), with a demo mode for the review (phase 8).
- **Presence-based delivery:** deciding between speaking and pushing by where the person is.

Also not in this first version: talking to Pebbo by voice in the app, approvals, routines, switching between home and office, widgets and quick actions, and summaries of text chats.

## Tests

- Core (`core/tests/test_phones.py`, offline with the network guard): pairing, single-use and expiring codes, wrong-code limit, hashed storage, token checks, immediate revocation, the access policy (app API from the home network yes, from public addresses no, control centre from the home network no), chat with a fake model including tools, history and model errors, scoping of one person's data, and due reminders.
- Control centre (`apps/web/src/control/Phones.test.tsx`): creating a pairing with code and local QR code, the warning when the core only listens locally, closing the code once used, and removing a phone.
- App (`apps/mobile/src/*.test.ts`) and contracts (`packages/contracts/src/phone.test.ts`): the API client, pairing from a QR link or typed input, stored credentials, chat messages and the pairing link.

Not tested automatically: the app's screens on a real device or simulator.
