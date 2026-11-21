import net from 'node:net';
import { expect, test } from 'vitest';
import { NetworkBlockedError } from './network-guard';

test('fetch to an external host is blocked', async () => {
  await expect(async () => fetch('https://example.com/')).rejects.toThrow(NetworkBlockedError);
});

test('raw sockets to an external host are blocked', () => {
  expect(() => net.connect({ host: '192.0.2.1', port: 443 })).toThrow(NetworkBlockedError);
});

test('WebSocket to an external host is blocked', () => {
  expect(() => new WebSocket('wss://example.com/')).toThrow(NetworkBlockedError);
});
