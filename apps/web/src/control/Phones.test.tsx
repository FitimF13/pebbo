import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import type { Person } from './api';
import { Phones } from './Phones';

const people: Person[] = [
  { id: 1, name: 'Alex', role: 'owner', voice_enabled: true, voice_samples: 3 },
  { id: 2, name: 'Sara', role: 'adult', voice_enabled: true, voice_samples: 0 },
];

function mockApi(options: { reachable?: boolean; open?: boolean } = {}) {
  const calls: { url: string; method: string; body?: unknown }[] = [];
  const expires = Date.now() / 1000 + 600;
  let paired = false;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET';
      calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      if (url === '/api/control/phones/pairings' && method === 'POST') {
        paired = true;
        return Response.json({
          id: 11, person_id: 2, expires_at: expires, code: '042817',
          addresses: ['http://192.168.1.20:8100', 'http://10.0.0.5:8100'], reachable: options.reachable ?? true,
        }, { status: 201 });
      }
      if (method !== 'GET') return new Response(null, { status: 204 });
      return Response.json({
        phones: [{ id: 5, person_id: 1, name: 'Alex iPhone', created_at: 0, last_seen_at: null }],
        pairings: paired && (options.open ?? true) ? [{ id: 11, person_id: 2, expires_at: expires }] : [],
      });
    }),
  );
  return calls;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test('creates a pairing for a person and shows the code with a local QR code', async () => {
  const calls = mockApi();
  render(<Phones people={people} />);

  expect(await screen.findByText('Alex iPhone')).toBeDefined();
  fireEvent.change(screen.getByLabelText('Handy koppeln für'), { target: { value: '2' } });
  fireEvent.click(screen.getByRole('button', { name: 'Code erstellen' }));

  expect((await screen.findByLabelText('Kopplungscode')).textContent).toBe('042 817');
  expect(screen.getByRole('img', { name: 'QR-Code zum Koppeln für Sara' })).toBeDefined();
  expect(calls).toContainEqual({ url: '/api/control/phones/pairings', method: 'POST', body: { person_id: 2 } });
  expect(screen.queryByRole('note')).toBeNull();
  // Only the core is contacted, never a QR service.
  expect(calls.every((call) => call.url.startsWith('/api/control/'))).toBe(true);

  fireEvent.change(screen.getByLabelText('Adresse'), { target: { value: 'http://10.0.0.5:8100' } });
  fireEvent.click(screen.getByRole('button', { name: 'Abbrechen' }));
  await waitFor(() => expect(calls).toContainEqual({ url: '/api/control/phones/pairings/11', method: 'DELETE', body: undefined }));
  expect(await screen.findByRole('button', { name: 'Code erstellen' })).toBeDefined();
});

test('warns when phones cannot reach the core', async () => {
  mockApi({ reachable: false });
  render(<Phones people={people} />);

  fireEvent.click(await screen.findByRole('button', { name: 'Code erstellen' }));
  expect((await screen.findByRole('note')).textContent).toContain('PEBBO_HOST=0.0.0.0');
});

test('hides the code once the phone used it', async () => {
  mockApi({ open: false });
  render(<Phones people={people} />);

  fireEvent.click(await screen.findByRole('button', { name: 'Code erstellen' }));
  await waitFor(() => expect(screen.queryByLabelText('Kopplungscode')).toBeNull());
  expect(screen.getByRole('button', { name: 'Code erstellen' })).toBeDefined();
});

test('removes a paired phone at once', async () => {
  const calls = mockApi();
  render(<Phones people={people} />);

  fireEvent.click(await screen.findByRole('button', { name: 'Entkoppeln' }));
  await waitFor(() => expect(calls).toContainEqual({ url: '/api/control/phones/5', method: 'DELETE', body: undefined }));
});
