/**
 * Pebbo's face as parameters, shared by the PC app, the phone app and (later) the device
 * renderer, so every Pebbo looks the same.
 */

/** Emotions the language model tags its replies with (see core/src/pebbo/voice/emotion.py). */
export const EMOTIONS = [
  'happy',
  'laughing',
  'surprised',
  'sad',
  'embarrassed',
  'sulky',
  'proud',
  'curious',
  'neutral',
] as const;

export type Emotion = (typeof EMOTIONS)[number];

export type Expression = Emotion | 'sleeping' | 'listening' | 'thinking';

export type EyeShape = 'open' | 'happy' | 'closed' | 'flat' | 'sad';
export type MouthShape = 'smile' | 'grin' | 'open' | 'small' | 'flat' | 'frown' | 'o';

export interface FaceParams {
  eyes: EyeShape;
  /** 1 is a normal eye, larger values look surprised or attentive. */
  eyeScale: number;
  /** Gaze offset in face units, x to the right and y down. */
  gaze: { x: number; y: number };
  mouth: MouthShape;
  /** 0 to 1. */
  blush: number;
  /** Little lines on the cheeks, as in the concept art. */
  blushLines: boolean;
}

const base: FaceParams = { eyes: 'open', eyeScale: 1, gaze: { x: 0, y: 0 }, mouth: 'smile', blush: 0.35, blushLines: false };

export const FACES: Record<Expression, FaceParams> = {
  neutral: base,
  happy: { ...base, eyes: 'happy', mouth: 'grin', blush: 0.6, blushLines: true },
  laughing: { ...base, eyes: 'happy', mouth: 'open', blush: 0.75, blushLines: true },
  surprised: { ...base, eyeScale: 1.3, mouth: 'o', blush: 0.3 },
  sad: { ...base, eyes: 'sad', mouth: 'frown', blush: 0.15, gaze: { x: 0, y: 3 } },
  embarrassed: { ...base, eyes: 'happy', mouth: 'small', blush: 1, blushLines: true, gaze: { x: -4, y: 2 } },
  sulky: { ...base, eyes: 'flat', mouth: 'flat', blush: 0.2, gaze: { x: 5, y: 0 } },
  proud: { ...base, eyes: 'closed', mouth: 'grin', blush: 0.5 },
  curious: { ...base, eyeScale: 1.15, gaze: { x: 4, y: -3 }, mouth: 'small' },
  sleeping: { ...base, eyes: 'closed', mouth: 'small', blush: 0.2 },
  listening: { ...base, eyeScale: 1.15, mouth: 'small', blush: 0.4 },
  thinking: { ...base, gaze: { x: 5, y: -6 }, mouth: 'flat', blush: 0.3 },
};

export function isEmotion(value: unknown): value is Emotion {
  return typeof value === 'string' && (EMOTIONS as readonly string[]).includes(value);
}
