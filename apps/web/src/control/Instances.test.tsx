import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { Instances } from './Instances';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test('shows a pending handoff and approves it', async () => {
  const calls: { url: string; method: string; body: string | undefined }[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method ?? 'GET', body: init?.body as string | undefined });
      if (init?.method === 'POST') return new Response(JSON.stringify({}), { status: 200 });
      return new Response(
        JSON.stringify({
          name: 'Büro',
          address: 'http://10.0.0.5:8100',
          peers: [{ id: 1, name: 'Zuhause', address: 'http://192.168.1.10:8100', created_at: 0 }],
          handoffs: [
            { id: 4, peer: 'Zuhause', direction: 'out', person: 'Alex', content: 'Offerte nachfassen', status: 'pending', created_at: 0 },
          ],
        }),
        { status: 200 },
      );
    }),
  );
  render(<Instances />);

  expect(await screen.findAllByText('Offerte nachfassen')).toBeDefined();
  expect(screen.getByText('http://192.168.1.10:8100')).toBeDefined();
  fireEvent.click(screen.getByRole('button', { name: 'Freigeben und senden' }));
  await waitFor(() =>
    expect(calls).toContainEqual({ url: '/api/control/instances/handoffs/4', method: 'POST', body: '{"approve":true}' }),
  );
});
