/** The phone's token lives in the Keychain (iOS) or the Keystore (Android), never in plain storage. */
import * as SecureStore from 'expo-secure-store';
import type { CredentialStore } from './pairing';

const KEY = 'pebbo.credentials';
// Only on this device, not in backups or on other devices of the same account.
const OPTIONS: SecureStore.SecureStoreOptions = { keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY };

export const secureCredentials: CredentialStore = {
  load: () => SecureStore.getItemAsync(KEY, OPTIONS),
  save: (value) => SecureStore.setItemAsync(KEY, value, OPTIONS),
  clear: () => SecureStore.deleteItemAsync(KEY, OPTIONS),
};
