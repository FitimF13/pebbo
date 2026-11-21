import { describe, expect, test } from 'vitest';
import { parseMessage } from './rtvi';
import { cleanCaption } from './usePebbo';

const message = (type: string, data?: object) => JSON.stringify({ label: 'rtvi-ai', type, data });

describe('parseMessage', () => {
  test('maps speaking and thinking events', () => {
    expect(parseMessage(message('user-started-speaking'))).toEqual({ kind: 'user-speaking', speaking: true });
    expect(parseMessage(message('bot-stopped-speaking'))).toEqual({ kind: 'bot-speaking', speaking: false });
    expect(parseMessage(message('bot-llm-started'))).toEqual({ kind: 'thinking' });
  });

  test('keeps only final transcripts', () => {
    expect(parseMessage(message('user-transcription', { text: ' Hallo ', final: true }))).toEqual({ kind: 'heard', text: 'Hallo' });
    expect(parseMessage(message('user-transcription', { text: 'Hal', final: false }))).toBeUndefined();
  });

  test('reads wake and emotion server messages and rejects unknown emotions', () => {
    expect(parseMessage(message('server-message', { type: 'wake', state: 'awake' }))).toEqual({ kind: 'wake', awake: true });
    expect(parseMessage(message('server-message', { type: 'emotion', emotion: 'proud' }))).toEqual({ kind: 'emotion', emotion: 'proud' });
    expect(parseMessage(message('server-message', { type: 'emotion', emotion: 'evil' }))).toBeUndefined();
  });

  test('ignores foreign or broken messages', () => {
    expect(parseMessage('not json')).toBeUndefined();
    expect(parseMessage(JSON.stringify({ label: 'other', type: 'bot-ready' }))).toBeUndefined();
  });
});


test('captions drop emphasis markers and emojis', () => {
  expect(cleanCaption('aber ich *weiss* es! 😊')).toBe('aber ich weiss es! ');
});
