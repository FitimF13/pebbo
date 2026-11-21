/** Client for the control centre API of the Pebbo core. */

export type Role = 'owner' | 'adult' | 'child' | 'colleague';

export interface Person {
  id: number;
  name: string;
  role: Role;
  voice_enabled: boolean;
  voice_samples: number;
}

export interface Memory {
  id: number;
  person_id: number | null;
  kind: 'fact' | 'preference' | 'summary';
  text: string;
  source: string;
  created_at: number;
}

export interface Reminder {
  id: number;
  person_id: number;
  text: string;
  due_at: number;
  due_text: string;
}

export interface VoiceClaim {
  id: number;
  claimed_name: string;
  person_id: number | null;
  created_at: number;
}

export interface Device {
  id: number;
  name: string;
  board: string;
  status: 'pending' | 'paired';
  online: boolean;
  last_seen_at: number | null;
}

export const ROLE_NAMES: Record<Role, string> = {
  owner: 'Besitzer',
  adult: 'Erwachsen',
  child: 'Kind',
  colleague: 'Kollege',
};

const BASE = '/api/control';

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const options: RequestInit = { ...init };
  if (init?.body) options.headers = { 'Content-Type': 'application/json' };
  const response = await fetch(`${BASE}${path}`, options);
  if (!response.ok) {
    const detail = await response.json().catch(() => undefined) as { detail?: unknown } | undefined;
    throw new Error(typeof detail?.detail === 'string' ? detail.detail : 'Das hat nicht geklappt.');
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

export const send = (method: string, body?: unknown): RequestInit =>
  body === undefined ? { method } : { method, body: JSON.stringify(body) };

export const controlApi = {
  people: () => request<Person[]>('/people'),
  addPerson: (name: string, role: Role) => request<Person>('/people', send('POST', { name, role })),
  updatePerson: (id: number, patch: { name?: string; voice_enabled?: boolean }) =>
    request<Person>(`/people/${id}`, send('PATCH', patch)),
  removePerson: (id: number) => request<void>(`/people/${id}`, send('DELETE')),
  resetVoice: (id: number) => request<void>(`/people/${id}/voice`, send('DELETE')),
  voiceClaims: () => request<VoiceClaim[]>('/voice-claims'),
  confirmClaim: (id: number, personId: number) =>
    request<void>(`/voice-claims/${id}/confirm`, send('POST', { person_id: personId })),
  rejectClaim: (id: number) => request<void>(`/voice-claims/${id}`, send('DELETE')),
  memories: () => request<Memory[]>('/memories'),
  addMemory: (personId: number | null, text: string) =>
    request<Memory>('/memories', send('POST', { person_id: personId, text })),
  updateMemory: (id: number, text: string) => request<void>(`/memories/${id}`, send('PATCH', { text })),
  deleteMemory: (id: number) => request<void>(`/memories/${id}`, send('DELETE')),
  reminders: () => request<Reminder[]>('/reminders'),
  cancelReminder: (id: number) => request<void>(`/reminders/${id}`, send('DELETE')),
  devices: () => request<Device[]>('/devices'),
  pairDevice: (code: string) => request<Device>('/devices/pair', send('POST', { code })),
  renameDevice: (id: number, name: string) => request<Device>(`/devices/${id}`, send('PATCH', { name })),
  removeDevice: (id: number) => request<void>(`/devices/${id}`, send('DELETE')),
};
