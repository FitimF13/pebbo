/**
 * Blocks every network connection in tests except loopback, so no test can silently
 * reach an external service. See docs/development.md.
 */
import net from 'node:net';

const loopback = new Set(['localhost', '127.0.0.1', '::1', '[::1]']);

export class NetworkBlockedError extends Error {
  constructor(target: string) {
    super(`Network access to ${target} is blocked in tests. Only loopback is allowed.`);
    this.name = 'NetworkBlockedError';
  }
}

function assertLoopback(host: string | undefined) {
  if (host && !loopback.has(host)) throw new NetworkBlockedError(host);
}

const connect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function guardedConnect(this: net.Socket, ...args: unknown[]) {
  // net.connect() passes its normalised arguments as a single array.
  const [first, second] = Array.isArray(args[0]) ? (args[0] as unknown[]) : args;
  if (typeof first === 'object' && first !== null && 'host' in first) {
    assertLoopback((first as net.TcpNetConnectOpts).host ?? undefined);
  } else if (typeof second === 'string') {
    assertLoopback(second);
  }
  return Reflect.apply(connect, this, args) as net.Socket;
} as typeof net.Socket.prototype.connect;

const realFetch = globalThis.fetch;
globalThis.fetch = (input, init) => {
  const url = new URL(input instanceof Request ? input.url : String(input), 'http://localhost');
  assertLoopback(url.hostname);
  return realFetch(input, init);
};

class BlockedWebSocket {
  constructor(url: string | URL) {
    const { hostname } = new URL(String(url));
    assertLoopback(hostname);
    throw new NetworkBlockedError(`${hostname} (WebSocket is not available in tests)`);
  }
}
globalThis.WebSocket = BlockedWebSocket as unknown as typeof WebSocket;
