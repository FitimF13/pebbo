import type { Emotion, Expression } from '@pebbo/contracts';

// The face parameters are shared with the phone app.
export { FACES, type EyeShape, type Expression, type FaceParams, type MouthShape } from '@pebbo/contracts';

export interface PebboState {
  connected: boolean;
  awake: boolean;
  userSpeaking: boolean;
  thinking: boolean;
  botSpeaking: boolean;
  emotion?: Emotion | undefined;
  /** Whether the last emotion is still shown after Pebbo finished speaking. */
  emotionLingers: boolean;
}

/** Decide which expression Pebbo shows for the current conversation state. */
export function expressionFor(state: PebboState): Expression {
  if (!state.connected) return 'sleeping';
  if (state.botSpeaking) return state.emotion ?? 'happy';
  if (state.userSpeaking) return 'listening';
  if (state.thinking) return 'thinking';
  if (!state.awake) return 'sleeping';
  if (state.emotion && state.emotionLingers) return state.emotion;
  return 'neutral';
}
