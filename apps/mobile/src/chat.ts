/** The chat on the phone: messages as shown, built from the core's replies. */
import { isEmotion, type ChatResponse, type Emotion } from '@pebbo/contracts';

export interface ChatMessage {
  id: string;
  from: 'me' | 'pebbo';
  text: string;
  /** What Pebbo did, shown as small confirmations under its answer. */
  actions: string[];
  /** A message of the person that did not reach Pebbo. */
  failed?: boolean;
}

/** Only the last messages stay on screen. The core keeps its own short history per phone. */
export const VISIBLE_MESSAGES = 50;

let counter = 0;
const nextId = () => `${Date.now().toString(36)}-${(counter += 1)}`;

export function myMessage(text: string): ChatMessage {
  return { id: nextId(), from: 'me', text: text.trim(), actions: [] };
}

export function pebboMessage(reply: ChatResponse): ChatMessage {
  return { id: nextId(), from: 'pebbo', text: reply.answer, actions: reply.actions };
}

export function emotionOf(reply: ChatResponse): Emotion {
  return isEmotion(reply.emotion) ? reply.emotion : 'neutral';
}

export function appendMessages(messages: ChatMessage[], ...added: ChatMessage[]): ChatMessage[] {
  return [...messages, ...added].slice(-VISIBLE_MESSAGES);
}

export function markFailed(messages: ChatMessage[], id: string): ChatMessage[] {
  return messages.map((message) => (message.id === id ? { ...message, failed: true } : message));
}
