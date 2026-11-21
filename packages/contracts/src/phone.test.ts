import { describe, expect, test } from 'vitest';
import { isPairingCode, normalizeAddress, pairingLink, parsePairingLink } from './phone';

describe('pairing link', () => {
  test('round-trips the address and the code', () => {
    const link = pairingLink({ address: 'http://192.168.1.20:8100/', code: '042817' });
    expect(link).toBe('pebbo://pair?address=http%3A%2F%2F192.168.1.20%3A8100&code=042817');
    expect(parsePairingLink(link)).toEqual({ address: 'http://192.168.1.20:8100', code: '042817' });
  });

  test('rejects links that are not Pebbo pairings', () => {
    expect(parsePairingLink('https://example.org/pair?address=x&code=123456')).toBeUndefined();
    expect(parsePairingLink('pebbo://other?address=http://10.0.0.2:8100&code=123456')).toBeUndefined();
    expect(parsePairingLink('pebbo://pair?address=http://10.0.0.2:8100&code=12345')).toBeUndefined();
    expect(parsePairingLink('pebbo://pair?address=ftp://10.0.0.2&code=123456')).toBeUndefined();
    expect(parsePairingLink('kein link')).toBeUndefined();
  });
});

describe('normalizeAddress', () => {
  test('adds the scheme and the default port to a typed host', () => {
    expect(normalizeAddress(' 192.168.1.20 ')).toBe('http://192.168.1.20:8100');
    expect(normalizeAddress('pebbo.local:9000')).toBe('http://pebbo.local:9000');
    expect(normalizeAddress('http://pebbo.local:8100/')).toBe('http://pebbo.local:8100');
    expect(normalizeAddress('[fd00::12]')).toBe('http://[fd00::12]:8100');
  });

  test('refuses what is not an http address', () => {
    expect(() => normalizeAddress('')).toThrow();
    expect(() => normalizeAddress('ftp://pebbo.local')).toThrow();
  });

  test('checks pairing codes', () => {
    expect(isPairingCode('123456')).toBe(true);
    expect(isPairingCode('12345a')).toBe(false);
  });
});
