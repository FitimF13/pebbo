/** Messages the core sends over the WebRTC data channel (Pipecat's RTVI protocol). */

import { isEmotion, type Emotion } from '@pebbo/contracts';

export type { Emotion };

export const RTVI_LABEL = 'rtvi-ai';
export const RTVI_VERSION = '2.3.0';

export type PebboEvent =
  | { kind: 'ready' }
  | { kind: 'user-speaking'; speaking: boolean }
  | { kind: 'bot-speaking'; speaking: boolean }
  | { kind: 'thinking' }
  | { kind: 'heard'; text: string }
  | { kind: 'says'; text: string }
  | { kind: 'wake'; awake: boolean }
  | { kind: 'emotion'; emotion: Emotion };

interface RtviMessage {
  label?: string;
  type?: string;
  data?: Record<string, unknown>;
}

/** Translate one raw data channel message into a Pebbo event, or nothing if it is irrelevant. */
export function parseMessage(raw: string): PebboEvent | undefined {
  let message: RtviMessage;
  try {
    message = JSON.parse(raw) as RtviMessage;
  } catch {
    return undefined;
  }
  if (message.label !== RTVI_LABEL) return undefined;
  const data = message.data ?? {};
  switch (message.type) {
    case 'bot-ready':
      return { kind: 'ready' };
    case 'user-started-speaking':
      return { kind: 'user-speaking', speaking: true };
    case 'user-stopped-speaking':
      return { kind: 'user-speaking', speaking: false };
    case 'bot-started-speaking':
      return { kind: 'bot-speaking', speaking: true };
    case 'bot-stopped-speaking':
      return { kind: 'bot-speaking', speaking: false };
    case 'bot-llm-started':
      return { kind: 'thinking' };
    case 'user-transcription':
      return data.final && typeof data.text === 'string' ? { kind: 'heard', text: data.text.trim() } : undefined;
    case 'bot-tts-text':
      return typeof data.text === 'string' ? { kind: 'says', text: data.text } : undefined;
    case 'server-message':
      return parseServerMessage(data);
    default:
      return undefined;
  }
}

function parseServerMessage(data: Record<string, unknown>): PebboEvent | undefined {
  if (data.type === 'wake') return { kind: 'wake', awake: data.state === 'awake' };
  if (data.type === 'emotion' && isEmotion(data.emotion)) {
    return { kind: 'emotion', emotion: data.emotion };
  }
  return undefined;
}

export function clientReadyMessage(): string {
  return JSON.stringify({
    label: RTVI_LABEL,
    type: 'client-ready',
    id: crypto.randomUUID(),
    data: { version: RTVI_VERSION, about: { library: 'pebbo-web' } },
  });
}
