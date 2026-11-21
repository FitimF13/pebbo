/**
 * The phone app API of the core (`/api/app/`, see core/src/pebbo/phones.py) and the
 * pairing link in the QR code, shared by the control centre and the phone app.
 */

export type Role = 'owner' | 'adult' | 'child' | 'colleague';

export interface PersonInfo {
  id: number;
  name: string;
  role: Role;
}

export interface PhoneInfo {
  id: number;
  name: string;
}

/** `POST /api/app/pair`: the phone exchanges the code once for its own token. */
export interface PairRequest {
  code: string;
  name: string;
}

export interface PairResponse {
  token: string;
  phone: PhoneInfo;
  person: PersonInfo;
}

/** `GET /api/app/me` */
export interface MeResponse {
  person: PersonInfo;
  phone: PhoneInfo;
  version: string;
}

export interface AppReminder {
  id: number;
  person_id: number;
  text: string;
  due_at: number;
  due_text: string;
}

export interface AppMemory {
  id: number;
  person_id: number | null;
  kind: 'fact' | 'preference' | 'summary';
  text: string;
  source: string;
  created_at: number;
}

/** `POST /api/app/chat` */
export interface ChatRequest {
  text: string;
}

export interface ChatResponse {
  answer: string;
  emotion: string;
  /** What Pebbo did, as short sentences, for example "Hab ich mir gemerkt: Mag Tee." */
  actions: string[];
}

/** `GET /api/app/notifications`: due reminders the phone has not acknowledged yet. */
export interface AppNotification {
  id: number;
  kind: 'reminder';
  text: string;
  due_at: number;
  due_text: string;
}

/** Control centre: `POST /api/control/phones/pairings` */
export interface NewPhonePairing {
  id: number;
  person_id: number;
  expires_at: number;
  code: string;
  addresses: string[];
  reachable: boolean;
}

export interface PhonePairing {
  id: number;
  person_id: number;
  expires_at: number;
}

export interface PairedPhone {
  id: number;
  person_id: number;
  name: string;
  created_at: number;
  last_seen_at: number | null;
}

/** Control centre: `GET /api/control/phones` */
export interface PhonesResponse {
  phones: PairedPhone[];
  pairings: PhonePairing[];
}

export const DEFAULT_PORT = 8100;
export const PAIRING_SCHEME = 'pebbo:';
const CODE = /^\d{6}$/;

export interface PairingTarget {
  address: string;
  code: string;
}

/** The link in the QR code. The phone's camera opens the Pebbo app with it. */
export function pairingLink({ address, code }: PairingTarget): string {
  const query = new URLSearchParams({ address: normalizeAddress(address), code });
  return `${PAIRING_SCHEME}//pair?${query.toString()}`;
}

/** Read a pairing link from the QR code, or `undefined` if it is not one. */
export function parsePairingLink(link: string): PairingTarget | undefined {
  let url: URL;
  try {
    url = new URL(link.trim());
  } catch {
    return undefined;
  }
  if (url.protocol !== PAIRING_SCHEME) return undefined;
  // "pebbo://pair?..." puts "pair" in the host, "pebbo:pair?..." in the path.
  const target = url.host || url.pathname.replace(/^\/+/, '');
  if (target !== 'pair') return undefined;
  const code = url.searchParams.get('code') ?? '';
  const address = url.searchParams.get('address') ?? '';
  if (!CODE.test(code) || !address) return undefined;
  try {
    return { address: normalizeAddress(address), code };
  } catch {
    return undefined;
  }
}

/**
 * Turn what someone typed, such as "192.168.1.20" or "http://pebbo.local:8100/", into the
 * core's base address. Throws for anything that is not an http address.
 */
export function normalizeAddress(input: string): string {
  const trimmed = input.trim();
  if (!trimmed) throw new Error('Gib die Adresse deines Pebbos ein.');
  const hasScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed);
  let url: URL;
  try {
    url = new URL(hasScheme ? trimmed : `http://${trimmed}`);
  } catch {
    throw new Error('Diese Adresse verstehe ich nicht.');
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') throw new Error('Die Adresse muss mit http:// beginnen.');
  if (!url.hostname) throw new Error('Diese Adresse verstehe ich nicht.');
  // Without a scheme, someone typed only the host, so the core's default port applies.
  const port = url.port || (hasScheme ? '' : String(DEFAULT_PORT));
  return `${url.protocol}//${url.hostname}${port ? `:${port}` : ''}`;
}

export function isPairingCode(code: string): boolean {
  return CODE.test(code);
}
