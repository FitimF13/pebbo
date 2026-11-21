// Runs the Expo CLI with its telemetry and online checks switched off (see docs/phone.md).
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';

const cli = createRequire(import.meta.url).resolve('expo/bin/cli');
const env = {
  ...process.env,
  // No usage data to Expo.
  EXPO_NO_TELEMETRY: '1',
  // No requests to Expo's servers, for example to sign the development manifest or check versions.
  EXPO_OFFLINE: '1',
};
const result = spawnSync(process.execPath, [cli, ...process.argv.slice(2)], { stdio: 'inherit', env });
process.exit(result.status ?? 1);
