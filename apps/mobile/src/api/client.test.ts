import { describe, expect, test } from 'vitest';
import { ApiError, createClient, pair, UNPAIRED, UNREACHABLE, type Fetch } from './client';

interface Call {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: unknown;
}

function fakeCore(reply: (call: Call) => Response): { fetch: Fetch; calls: Call[] } {
  const calls: Call[] = [];
  const fetch: Fetch = async (url, init) => {
    const call = {
      url,
      method: init?.method ?? 'GET',
      headers: (init?.headers ?? {}) as Record<string, string>,
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    };
    calls.push(call);
    return reply(call);
  };
  return { fetch, calls };
}

const ADDRESS = 'http://192.168.1.20:8100';

describe('createClient', () => {
  test('sends the token with every request to the paired Pebbo only', async () => {
    const core = fakeCore((call) =>
      call.url.endsWith('/chat')
        ? Response.json({ answer: 'Gern!', emotion: 'happy', actions: ['Hab ich mir gemerkt: Mag Tee.'] })
        : call.method === 'DELETE' || call.url.endsWith('/ack')
          ? new Response(null, { status: 204 })
          : Response.json([]),
    );
    const client = createClient({ address: ADDRESS, token: 'geheim', fetch: core.fetch });

    const reply = await client.chat('Merk dir, ich mag Tee');
    await client.reminders();
    await client.deleteMemory(5);
    await client.acknowledge(1700000000);

    expect(reply.actions).toEqual(['Hab ich mir gemerkt: Mag Tee.']);
    expect(core.calls.map((call) => `${call.method} ${call.url}`)).toEqual([
      `POST ${ADDRESS}/api/app/chat`,
      `GET ${ADDRESS}/api/app/reminders`,
      `DELETE ${ADDRESS}/api/app/memories/5`,
      `POST ${ADDRESS}/api/app/notifications/ack`,
    ]);
    expect(core.calls.every((call) => call.headers.Authorization === 'Bearer geheim')).toBe(true);
    expect(core.calls[0]?.body).toEqual({ text: 'Merk dir, ich mag Tee' });
    expect(core.calls[3]?.body).toEqual({ until: 1700000000 });
  });

  test('reports a removed phone, server messages and an unreachable core', async () => {
    const removed = createClient({ address: ADDRESS, token: 'alt', fetch: fakeCore(() => new Response('{}', { status: 401 })).fetch });
    const error = await removed.me().catch((cause: unknown) => cause);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).unpaired).toBe(true);
    expect((error as ApiError).message).toBe(UNPAIRED);

    const busy = createClient({
      address: ADDRESS,
      token: 't',
      fetch: fakeCore(() => Response.json({ detail: 'Pebbo kann gerade nicht nachdenken.' }, { status: 503 })).fetch,
    });
    await expect(busy.chat('Hoi')).rejects.toThrow('Pebbo kann gerade nicht nachdenken.');

    const offline = createClient({
      address: ADDRESS,
      token: 't',
      fetch: () => Promise.reject(new TypeError('Network request failed')),
    });
    await expect(offline.memories()).rejects.toMatchObject({ status: 0, message: UNREACHABLE });
  });
});

test('pair sends the code and the phone name without a token', async () => {
  const core = fakeCore(() =>
    Response.json({ token: 'neu', phone: { id: 3, name: 'Saras Handy' }, person: { id: 2, name: 'Sara', role: 'adult' } }),
  );

  const reply = await pair(core.fetch, ADDRESS, '042817', 'Saras Handy');

  expect(reply.token).toBe('neu');
  expect(core.calls[0]).toMatchObject({ url: `${ADDRESS}/api/app/pair`, method: 'POST', body: { code: '042817', name: 'Saras Handy' } });
  expect(core.calls[0]?.headers.Authorization).toBeUndefined();
});
