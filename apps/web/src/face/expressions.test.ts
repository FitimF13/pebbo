import { describe, expect, test } from 'vitest';
import { expressionFor, type PebboState } from './expressions';

const awake: PebboState = {
  connected: true, awake: true, userSpeaking: false, thinking: false, botSpeaking: false, emotionLingers: false,
};

describe('expressionFor', () => {
  test('sleeps when disconnected or not woken up', () => {
    expect(expressionFor({ ...awake, connected: false })).toBe('sleeping');
    expect(expressionFor({ ...awake, awake: false })).toBe('sleeping');
  });

  test('listens, thinks and speaks with the reply emotion', () => {
    expect(expressionFor({ ...awake, userSpeaking: true })).toBe('listening');
    expect(expressionFor({ ...awake, thinking: true })).toBe('thinking');
    expect(expressionFor({ ...awake, botSpeaking: true, emotion: 'surprised' })).toBe('surprised');
    expect(expressionFor({ ...awake, botSpeaking: true })).toBe('happy');
  });

  test('keeps the emotion briefly after speaking, then relaxes', () => {
    expect(expressionFor({ ...awake, emotion: 'proud', emotionLingers: true })).toBe('proud');
    expect(expressionFor({ ...awake, emotion: 'proud', emotionLingers: false })).toBe('neutral');
  });
});
