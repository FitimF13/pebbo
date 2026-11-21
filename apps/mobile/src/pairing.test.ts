import { describe, expect, test } from 'vitest';
import { pairingLink, parsePairingLink, type AppNotification } from '@pebbo/contracts';
import type { Fetch } from './api/client';
import { appendMessages, emotionOf, markFailed, myMessage, pebboMessage, VISIBLE_MESSAGES } from './chat';
import { loadCredentials, pairPhone, unpairPhone, type CredentialStore } from './pairing';
import { acknowledgedUntil } from './pending';

function memoryStore(initial: string | null = null): CredentialStore & { value: string | null } {
  const store = {
    value: initial,
    load: async () => store.value,
    save: async (value: string) => {
      store.value = value;
    },
    clear: async () => {
      store.value = null;
    },
  };
  return store;
}

const paired: Fetch = async (url, init) => {
  const { code, name } = JSON.parse(String(init?.body)) as { code: string; name: string };
  if (!url.endsWith('/api/app/pair') || code !== '042817') return Response.json({ detail: 'Falscher Code.' }, { status: 404 });
  return Response.json({ token: 'tok', phone: { id: 7, name }, person: { id: 2, name: 'Sara', role: 'adult' } });
};

describe('pairPhone', () => {
  test('pairs from the scanned QR code and keeps the token in the store', async () => {
    const target = parsePairingLink(pairingLink({ address: 'http://192.168.1.20:8100', code: '042817' }));
    expect(target).toBeDefined();
    const store = memoryStore();

    const credentials = await pairPhone({ ...target!, name: '  Saras Handy ' }, { fetch: paired, store });

    expect(credentials).toEqual({
      address: 'http://192.168.1.20:8100',
      token: 'tok',
      phoneId: 7,
      phoneName: 'Saras Handy',
      person: { id: 2, name: 'Sara', role: 'adult' },
    });
    expect(await loadCredentials(store)).toEqual(credentials);
  });

  test('accepts a typed address and a code with spaces', async () => {
    const store = memoryStore();
    const credentials = await pairPhone({ address: '192.168.1.20', code: '042 817', name: '' }, { fetch: paired, store });
    expect(credentials.address).toBe('http://192.168.1.20:8100');
    expect(credentials.phoneName).toBe('Mein Handy');
  });

  test('stores nothing when the code is wrong or malformed', async () => {
    const store = memoryStore();
    await expect(pairPhone({ address: '192.168.1.20', code: '111111', name: 'x' }, { fetch: paired, store })).rejects.toThrow(
      'Falscher Code.',
    );
    await expect(pairPhone({ address: '192.168.1.20', code: '123', name: 'x' }, { fetch: paired, store })).rejects.toThrow(
      'sechs Ziffern',
    );
    await expect(pairPhone({ address: '', code: '042817', name: 'x' }, { fetch: paired, store })).rejects.toThrow();
    expect(store.value).toBeNull();
  });
});

describe('stored credentials', () => {
  test('broken credentials count as not paired and are removed', async () => {
    const store = memoryStore('{"address": 3}');
    expect(await loadCredentials(store)).toBeUndefined();
    expect(store.value).toBeNull();
    expect(await loadCredentials(memoryStore('kein json'))).toBeUndefined();
  });

  test('unpairing forgets the token even when Pebbo is unreachable', async () => {
    const store = memoryStore('{"token": "x"}');
    await unpairPhone(() => Promise.reject(new Error('offline')), store);
    expect(store.value).toBeNull();
  });
});

describe('chat messages', () => {
  test('keeps Pebbo’s actions and a known emotion', () => {
    const reply = { answer: 'Gern!', emotion: 'happy', actions: ['Hab ich mir gemerkt: Mag Tee.'] };
    expect(pebboMessage(reply)).toMatchObject({ from: 'pebbo', text: 'Gern!', actions: reply.actions });
    expect(emotionOf(reply)).toBe('happy');
    expect(emotionOf({ ...reply, emotion: 'ignore' })).toBe('neutral');
  });

  test('marks failed messages and keeps only the latest on screen', () => {
    const first = myMessage(' Hallo ');
    expect(first.text).toBe('Hallo');
    expect(markFailed([first], first.id)[0]?.failed).toBe(true);
    const many = Array.from({ length: VISIBLE_MESSAGES + 5 }, (_, n) => myMessage(`Nachricht ${n}`));
    const shown = appendMessages([], ...many);
    expect(shown).toHaveLength(VISIBLE_MESSAGES);
    expect(shown.at(-1)?.text).toBe(`Nachricht ${VISIBLE_MESSAGES + 4}`);
  });
});

test('acknowledges up to the latest reminder shown', () => {
  const due = (id: number, at: number): AppNotification => ({ id, kind: 'reminder', text: 'x', due_at: at, due_text: '' });
  expect(acknowledgedUntil([])).toBeUndefined();
  expect(acknowledgedUntil([due(1, 20), due(2, 50), due(3, 30)])).toBe(50);
});
