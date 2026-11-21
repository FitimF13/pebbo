/**
 * Client for the core's phone app API (`/api/app/`, see core/src/pebbo/phones.py).
 *
 * It talks only to the Pebbo it was paired with. `fetch` is passed in, so the client can be
 * tested without a network.
 */
import type {
  AppMemory,
  AppNotification,
  AppReminder,
  ChatResponse,
  MeResponse,
  PairResponse,
} from '@pebbo/contracts';

export type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

export const UNREACHABLE = 'Pebbo ist gerade nicht erreichbar. Bist du im gleichen WLAN wie Pebbo?';
export const UNPAIRED = 'Dieses Handy ist nicht mehr mit Pebbo gekoppelt.';
const FAILED = 'Das hat nicht geklappt.';
const TIMEOUT_MS = 15_000;
// Pebbo thinks and acts before it answers, which can take a while on a small computer.
const CHAT_TIMEOUT_MS = 90_000;

export class ApiError extends Error {
  constructor(
    message: string,
    /** The HTTP status, or 0 if the core could not be reached. */
    readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }

  /** The core no longer knows this phone: it was removed in the control centre. */
  get unpaired(): boolean {
    return this.status === 401;
  }
}

async function call<T>(
  fetchImpl: Fetch,
  url: string,
  init: RequestInit,
  timeoutMs: number = TIMEOUT_MS,
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    response = await fetchImpl(url, { ...init, signal: controller.signal });
  } catch {
    throw new ApiError(UNREACHABLE, 0);
  } finally {
    clearTimeout(timer);
  }
  if (!response.ok) {
    if (response.status === 401) throw new ApiError(UNPAIRED, 401);
    const body = (await response.json().catch(() => undefined)) as { detail?: unknown } | undefined;
    throw new ApiError(typeof body?.detail === 'string' ? body.detail : FAILED, response.status);
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

function json(method: string, body?: unknown, headers: Record<string, string> = {}): RequestInit {
  return body === undefined
    ? { method, headers }
    : { method, headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
}

/** Exchange a pairing code once for this phone's own token. */
export function pair(fetchImpl: Fetch, address: string, code: string, name: string): Promise<PairResponse> {
  return call<PairResponse>(fetchImpl, `${address}/api/app/pair`, json('POST', { code, name }));
}

export interface ClientOptions {
  address: string;
  token: string;
  fetch: Fetch;
}

export type AppClient = ReturnType<typeof createClient>;

/** The API for a paired phone. Every request carries the phone's token. */
export function createClient({ address, token, fetch: fetchImpl }: ClientOptions) {
  const auth = { Authorization: `Bearer ${token}` };
  const request = <T>(method: string, path: string, body?: unknown, timeoutMs?: number) =>
    call<T>(fetchImpl, `${address}/api/app${path}`, json(method, body, auth), timeoutMs);

  return {
    me: () => request<MeResponse>('GET', '/me'),
    unpair: () => request<void>('DELETE', '/me'),
    reminders: () => request<AppReminder[]>('GET', '/reminders'),
    cancelReminder: (id: number) => request<void>('DELETE', `/reminders/${id}`),
    memories: () => request<AppMemory[]>('GET', '/memories'),
    deleteMemory: (id: number) => request<void>('DELETE', `/memories/${id}`),
    chat: (text: string) => request<ChatResponse>('POST', '/chat', { text }, CHAT_TIMEOUT_MS),
    notifications: () => request<AppNotification[]>('GET', '/notifications'),
    acknowledge: (until: number) => request<void>('POST', '/notifications/ack', { until }),
  };
}
