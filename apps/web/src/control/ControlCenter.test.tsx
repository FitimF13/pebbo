import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { ControlCenter } from './ControlCenter';

const responses: Record<string, unknown> = {
  '/api/control/people': [
    { id: 1, name: 'Alex', role: 'owner', voice_enabled: true, voice_samples: 3 },
    { id: 2, name: 'Sara', role: 'adult', voice_enabled: true, voice_samples: 0 },
  ],
  '/api/control/voice-claims': [{ id: 7, claimed_name: 'Sara', person_id: 2, created_at: 0 }],
  '/api/control/memories': [
    { id: 5, person_id: 1, kind: 'fact', text: 'Mag Kaffee ohne Zucker', source: 'said', created_at: 0 },
    { id: 6, person_id: 1, kind: 'fact', text: 'Bruder heisst Leon', source: 'learned', created_at: 0 },
  ],
  '/api/control/reminders': [{ id: 9, person_id: 1, text: 'Paket mitnehmen', due_at: 0, due_text: 'morgen um 07:30' }],
  '/api/control/phones': { phones: [], pairings: [] },
  '/api/control/devices': [
    { id: 3, name: 'Wohnzimmer', board: 'esp-box-3', status: 'paired', online: true, last_seen_at: 0 },
    { id: 4, name: 'Pebbo', board: 'esp-box-3', status: 'pending', online: false, last_seen_at: null },
  ],
};

function mockApi() {
  const calls: { url: string; method: string }[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method ?? 'GET' });
      if (init?.method && init.method !== 'GET') return new Response(null, { status: 204 });
      return new Response(JSON.stringify(responses[url] ?? []), { status: 200 });
    }),
  );
  return calls;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test('shows people with voice status and a pending voice claim', async () => {
  const calls = mockApi();
  render(<ControlCenter onClose={() => undefined} />);

  expect(await screen.findByText('Stimme bekannt · 3 Proben')).toBeDefined();
  expect(screen.getByText('Stimme noch unbekannt')).toBeDefined();
  fireEvent.click(screen.getByRole('button', { name: 'Ja, das ist Sara' }));
  await waitFor(() => expect(calls).toContainEqual({ url: '/api/control/voice-claims/7/confirm', method: 'POST' }));
});

test('lists memories and reminders in their tabs', async () => {
  mockApi();
  render(<ControlCenter onClose={() => undefined} />);

  fireEvent.click(await screen.findByRole('button', { name: 'Gedächtnis' }));
  expect(screen.getByText('Mag Kaffee ohne Zucker')).toBeDefined();
  expect(screen.getByText('Nebenbei gelernt')).toBeDefined();
  fireEvent.click(screen.getByRole('button', { name: 'Erinnerungen' }));
  expect(screen.getByText('Alex · morgen um 07:30')).toBeDefined();
});

test('pairs a body with the code from its screen', async () => {
  const calls = mockApi();
  render(<ControlCenter onClose={() => undefined} />);

  fireEvent.click(await screen.findByRole('button', { name: 'Geräte' }));
  expect(screen.getByText('Wohnzimmer')).toBeDefined();
  expect(screen.getByText(/Ein Gerät wartet gerade auf die Kopplung/)).toBeDefined();
  const input = screen.getByPlaceholderText('123456');
  fireEvent.change(input, { target: { value: '12a3456789' } });
  expect((input as HTMLInputElement).value).toBe('123456');
  fireEvent.click(screen.getByRole('button', { name: 'Koppeln' }));
  await waitFor(() => expect(calls).toContainEqual({ url: '/api/control/devices/pair', method: 'POST' }));
});

test('asks for the owner on first use', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('[]', { status: 200 })));
  render(<ControlCenter onClose={() => undefined} />);

  expect(await screen.findByText('Willkommen bei Pebbo')).toBeDefined();
});
