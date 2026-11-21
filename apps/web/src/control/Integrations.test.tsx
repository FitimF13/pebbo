import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { ControlCenter } from './ControlCenter';
import { Integrations, type Integration } from './Integrations';

const homeAssistant: Integration = {
  id: 1,
  name: 'Home Assistant',
  url: 'http://192.168.1.20:8123/api/mcp',
  permission: 'household',
  enabled: true,
  allow_public: false,
  has_token: true,
  public_host: null,
  status: {
    state: 'connected',
    message: '',
    tools: ['home_assistant_HassTurnOn', 'home_assistant_HassTurnOff'],
    live_context: true,
    checked_at: 0,
  },
};

const broken: Integration = {
  ...homeAssistant,
  id: 2,
  name: 'Werkstatt',
  url: 'https://203.0.113.9/mcp',
  permission: 'owner',
  has_token: false,
  allow_public: true,
  public_host: '203.0.113.9',
  status: { state: 'error', message: 'Der Server hat den Zugangstoken abgelehnt.', tools: [], live_context: false, checked_at: 0 },
};

interface Call {
  url: string;
  method: string;
  body?: unknown;
}

function mockApi(integrations: Integration[]) {
  const calls: Call[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET';
      calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      if (method === 'DELETE') return new Response(null, { status: 204 });
      if (method !== 'GET') return new Response(JSON.stringify(homeAssistant), { status: 200 });
      if (url === '/api/control/integrations') return new Response(JSON.stringify(integrations), { status: 200 });
      if (url === '/api/control/people') {
        return new Response(JSON.stringify([{ id: 1, name: 'Alex', role: 'owner', voice_enabled: true, voice_samples: 3 }]), {
          status: 200,
        });
      }
      return new Response('[]', { status: 200 });
    }),
  );
  return calls;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test('the control centre has an integrations tab', async () => {
  mockApi([homeAssistant]);
  render(<ControlCenter onClose={() => undefined} />);

  fireEvent.click(await screen.findByRole('button', { name: 'Integrationen' }));
  expect(await screen.findByText('2 Werkzeuge · kennt den Zustand der Geräte')).toBeDefined();
  expect(screen.getByText('Verbunden')).toBeDefined();
});

test('shows status, permission and allowed public hosts, never a token', async () => {
  mockApi([homeAssistant, broken]);
  render(<Integrations />);

  expect(await screen.findByText('Der Server hat den Zugangstoken abgelehnt.')).toBeDefined();
  expect(screen.getByText('Öffentliche Adresse erlaubt: 203.0.113.9')).toBeDefined();
  expect(screen.getByText('http://192.168.1.20:8123/api/mcp · Token gespeichert')).toBeDefined();
  expect(screen.getByText('https://203.0.113.9/mcp · Kein Token')).toBeDefined();
  const permission = screen.getByLabelText('Wer darf Werkstatt benutzen') as HTMLSelectElement;
  expect(permission.value).toBe('owner');
});

test('adds Home Assistant with a token, permission and the public switch off', async () => {
  const calls = mockApi([]);
  render(<Integrations />);

  expect(await screen.findByText(/Noch keine Integration/)).toBeDefined();
  const add = screen.getByRole('button', { name: 'Hinzufügen' }) as HTMLButtonElement;
  expect(add.disabled).toBe(true);
  fireEvent.change(screen.getByPlaceholderText('http://homeassistant.local:8123/api/mcp/assist'), {
    target: { value: 'http://192.168.1.20:8123/api/mcp' },
  });
  fireEvent.change(screen.getByPlaceholderText('Langlebiger Zugangstoken'), { target: { value: 'secret' } });
  fireEvent.click(add);

  await waitFor(() =>
    expect(calls).toContainEqual({
      url: '/api/control/integrations',
      method: 'POST',
      body: {
        name: 'Home Assistant',
        url: 'http://192.168.1.20:8123/api/mcp',
        token: 'secret',
        permission: 'household',
        allow_public: false,
      },
    }),
  );
  expect((screen.getByPlaceholderText('Langlebiger Zugangstoken') as HTMLInputElement).value).toBe('');
});

test('changes permission, reconnects, switches off and removes', async () => {
  const calls = mockApi([homeAssistant]);
  render(<Integrations />);

  const permission = await screen.findByLabelText('Wer darf Home Assistant benutzen');
  fireEvent.change(permission, { target: { value: 'owner' } });
  await waitFor(() =>
    expect(calls).toContainEqual({ url: '/api/control/integrations/1', method: 'PATCH', body: { permission: 'owner' } }),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Neu verbinden' }));
  await waitFor(() => expect(calls).toContainEqual({ url: '/api/control/integrations/1/refresh', method: 'POST' }));
  fireEvent.click(screen.getByRole('button', { name: 'Ausschalten' }));
  await waitFor(() =>
    expect(calls).toContainEqual({ url: '/api/control/integrations/1', method: 'PATCH', body: { enabled: false } }),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Token ändern' }));
  fireEvent.change(screen.getByLabelText('Neuer Token für Home Assistant'), { target: { value: 'new-token' } });
  fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
  await waitFor(() =>
    expect(calls).toContainEqual({ url: '/api/control/integrations/1', method: 'PATCH', body: { token: 'new-token' } }),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Entfernen' }));
  await waitFor(() => expect(calls).toContainEqual({ url: '/api/control/integrations/1', method: 'DELETE' }));
});
