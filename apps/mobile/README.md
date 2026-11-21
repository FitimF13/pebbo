# Pebbo phone app

Native iOS and Android app built with Expo and React Native: pairing, chat with Pebbo, reminders, memories and settings. How to pair, build and run it, and what is still open, is in [phone app](../../docs/phone.md).

```sh
pnpm --filter @pebbo/mobile typecheck
pnpm --filter @pebbo/mobile test
pnpm --filter @pebbo/mobile build   # offline export of the bundle for iOS and Android
pnpm --filter @pebbo/mobile ios     # development build, needs Xcode
pnpm --filter @pebbo/mobile android # development build, needs Android Studio
```

Always use these scripts. They start the Expo CLI with its telemetry and online checks switched off.
