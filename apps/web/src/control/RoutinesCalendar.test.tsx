import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import type { Person } from './api';
import { Calendar } from './Calendar';
import { Routines } from './Routines';

const people: Person[] = [
  { id: 1, name: 'Alex', role: 'owner', voice_enabled: true, voice_samples: 3 },
  { id: 2, name: 'Mia', role: 'child', voice_enabled: true, voice_samples: 1 },
];

const routine = {
  person_id: 1,
  text: '',
  needs_owner: false,
  waiting_for_owner: false,
  cooldown_minutes: 15,
  daily_limit: 6,
  created_at: 0,
  last_run_at: null,
};

const responses: Record<string, unknown> = {
  '/api/control/routines': [
    { ...routine, id: 1, name: 'Guten Morgen', status: 'active', description: 'Jeden Tag um 07:00 sage ich «Guten Morgen».' },
    {
      ...routine,
      id: 2,
      person_id: 2,
      name: 'Alex kommt',
      status: 'draft',
      needs_owner: true,
      waiting_for_owner: true,
      description: 'Wenn Alex heimkommt, sage ich «Hallo».',
    },
  ],
  '/api/control/routine-runs': [
    {
      id: 5,
      routine_id: 1,
      started_at: 0,
      trigger: 'Jeden Tag um 07:00',
      conditions: [{ text: 'gerade keine Ruhezeit ist', ok: true }],
      actions: [{ text: 'sage ich «Guten Morgen»', ok: true, outcome: 'spoken' }],
      result: 'done',
      dry_run: false,
    },
  ],
  '/api/control/routines/1/test': { say: 'Wenn «Guten Morgen» jetzt liefe, würde ich «Guten Morgen» sagen.', run: {} },
  '/api/control/calendar/events?days=14': [
    { event_id: 3, person_id: 1, source_id: null, title: 'Zahnarzt', start: 1795500000, end: null, all_day: false, recurring: false },
    { event_id: 4, person_id: null, source_id: 8, title: 'Schulfest', start: 1795500000, end: null, all_day: true, recurring: false },
  ],
  '/api/control/calendar/sources': [
    {
      id: 8,
      person_id: null,
      name: 'Schule',
      host: 'cal.example.test',
      external: true,
      allow_external: false,
      last_synced_at: null,
      last_error: null,
    },
  ],
};

function mockApi() {
  const calls: { url: string; method: string; body?: unknown }[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET';
      calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      if (method === 'DELETE') return new Response(null, { status: 204 });
      return new Response(JSON.stringify(responses[url] ?? {}), { status: 200 });
    }),
  );
  return calls;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test('lists routines, approves, pauses, tries and shows the run log', async () => {
  const calls = mockApi();
  render(<Routines people={people} />);

  expect(await screen.findByText('Jeden Tag um 07:00 sage ich «Guten Morgen».')).toBeDefined();
  expect(screen.getByText('Wartet auf Freigabe')).toBeDefined();
  expect(screen.getByText(/Mia · braucht die Freigabe des Besitzers/)).toBeDefined();

  fireEvent.click(screen.getByRole('button', { name: 'Freigeben' }));
  await waitFor(() =>
    expect(calls).toContainEqual({ url: '/api/control/routines/2/status', method: 'POST', body: { status: 'active' } }),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Pausieren' }));
  await waitFor(() =>
    expect(calls).toContainEqual({ url: '/api/control/routines/1/status', method: 'POST', body: { status: 'paused' } }),
  );
  fireEvent.click(screen.getAllByRole('button', { name: 'Testen' })[0]!);
  expect(await screen.findByText('Wenn «Guten Morgen» jetzt liefe, würde ich «Guten Morgen» sagen.')).toBeDefined();
  fireEvent.click(screen.getAllByRole('button', { name: 'Verlauf' })[0]!);
  expect(screen.getByText(/Ausgeführt/)).toBeDefined();
  expect(screen.getByText('✓ Aktion: sage ich «Guten Morgen» (spoken)')).toBeDefined();
});

test('shows appointments and keeps external calendars off until allowed', async () => {
  const calls = mockApi();
  render(<Calendar people={people} />);

  expect(await screen.findByText('Zahnarzt')).toBeDefined();
  expect(screen.getByText(/Ganztägig · Haushalt · abonniert/)).toBeDefined();
  expect(screen.getAllByRole('button', { name: 'Löschen' })).toHaveLength(1);
  expect((screen.getByRole('button', { name: 'Abgleichen' }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText(/cal.example.test · ausserhalb des Heimnetzes/)).toBeDefined();

  fireEvent.click(screen.getByRole('checkbox'));
  await waitFor(() =>
    expect(calls).toContainEqual({
      url: '/api/control/calendar/sources/8',
      method: 'PATCH',
      body: { allow_external: true },
    }),
  );

  fireEvent.change(screen.getByPlaceholderText('z. B. Zahnarzt'), { target: { value: 'Coiffeur' } });
  fireEvent.click(screen.getByRole('button', { name: 'Eintragen' }));
  await waitFor(() => expect(calls.some((call) => call.url === '/api/control/calendar/events' && call.method === 'POST')).toBe(true));
  const added = calls.find((call) => call.url === '/api/control/calendar/events' && call.method === 'POST');
  expect(added?.body).toMatchObject({ person_id: 1, title: 'Coiffeur' });
});
