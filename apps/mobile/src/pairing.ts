/**
 * Pairing this phone with a Pebbo: from the QR code's link or a typed address and code to
 * stored credentials. The token is kept in the platform's secure storage (see storage.ts).
 */
import { isPairingCode, normalizeAddress, type PersonInfo } from '@pebbo/contracts';
import { pair, type Fetch } from './api/client';

export interface Credentials {
  address: string;
  token: string;
  phoneId: number;
  phoneName: string;
  person: PersonInfo;
}

/** Where the credentials are kept. On the phone this is expo-secure-store. */
export interface CredentialStore {
  load(): Promise<string | null>;
  save(value: string): Promise<void>;
  clear(): Promise<void>;
}

export interface PairingInput {
  address: string;
  code: string;
  name: string;
}

export const DEFAULT_PHONE_NAME = 'Mein Handy';

/** Pair with the core and store the credentials. Throws an error with a German message. */
export async function pairPhone(
  input: PairingInput,
  deps: { fetch: Fetch; store: CredentialStore },
): Promise<Credentials> {
  const address = normalizeAddress(input.address);
  const code = input.code.replace(/\D/g, '');
  if (!isPairingCode(code)) throw new Error('Der Code hat sechs Ziffern.');
  const name = input.name.trim().slice(0, 40) || DEFAULT_PHONE_NAME;
  const reply = await pair(deps.fetch, address, code, name);
  const credentials: Credentials = {
    address,
    token: reply.token,
    phoneId: reply.phone.id,
    phoneName: reply.phone.name,
    person: reply.person,
  };
  await deps.store.save(JSON.stringify(credentials));
  return credentials;
}

/** The stored credentials, or `undefined` if this phone is not paired. */
export async function loadCredentials(store: CredentialStore): Promise<Credentials | undefined> {
  const raw = await store.load();
  if (!raw) return undefined;
  try {
    const value = JSON.parse(raw) as Partial<Credentials>;
    if (
      typeof value.address === 'string' &&
      typeof value.token === 'string' &&
      typeof value.phoneId === 'number' &&
      typeof value.phoneName === 'string' &&
      typeof value.person?.name === 'string'
    ) {
      return value as Credentials;
    }
  } catch {
    // Unreadable credentials are treated as not paired.
  }
  await store.clear();
  return undefined;
}

/** Unpair: tell the core if it is reachable, and forget the token in any case. */
export async function unpairPhone(unpair: () => Promise<void>, store: CredentialStore): Promise<void> {
  try {
    await unpair();
  } catch {
    // The core may be unreachable or may have removed the phone already.
  }
  await store.clear();
}
