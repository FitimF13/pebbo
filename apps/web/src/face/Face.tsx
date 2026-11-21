import { useEffect, useState } from 'react';
import { FACES, type EyeShape, type Expression, type MouthShape } from './expressions';

interface FaceProps {
  expression: Expression;
  /** Loudness of Pebbo's voice from 0 to 1, drives the mouth while speaking. */
  level: number;
  speaking: boolean;
}

const EYE_X = 60;
const EYE_Y = 50;

/** Pebbo's glowing screen face, drawn as SVG so it stays sharp on any display. */
export function Face({ expression, level, speaking }: FaceProps) {
  const face = FACES[expression];
  const blinking = useBlink(face.eyes === 'open');
  const idleGaze = useIdleGaze(expression === 'neutral');
  const gaze = { x: face.gaze.x + idleGaze.x, y: face.gaze.y + idleGaze.y };

  return (
    <svg className="face" viewBox="0 0 200 120" role="img" aria-label={`Pebbo: ${expression}`}>
      <defs>
        <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="2.2" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <g className="face-features" filter="url(#glow)" style={{ transform: `translate(${gaze.x}px, ${gaze.y}px)` }}>
        <Eye x={EYE_X} shape={blinking ? 'closed' : face.eyes} scale={face.eyeScale} />
        <Eye x={200 - EYE_X} shape={blinking ? 'closed' : face.eyes} scale={face.eyeScale} mirrored />
        <Cheek x={EYE_X - 20} blush={face.blush} lines={face.blushLines} />
        <Cheek x={200 - EYE_X + 20} blush={face.blush} lines={face.blushLines} />
        <Mouth shape={speaking ? 'open' : face.mouth} level={speaking ? level : 0} />
      </g>
      {expression === 'sleeping' && <Sleepy />}
    </svg>
  );
}

function Eye({ x, shape, scale, mirrored = false }: { x: number; shape: EyeShape; scale: number; mirrored?: boolean }) {
  const transform = `translate(${x} ${EYE_Y}) scale(${scale})`;
  switch (shape) {
    case 'happy':
      return <path className="eye-line" transform={transform} d="M -17 7 Q 0 -17 17 7" />;
    case 'closed':
      return <path className="eye-line" transform={transform} d="M -16 0 Q 0 12 16 0" />;
    case 'sad':
      return (
        <path className="eye-line" transform={`${transform}${mirrored ? ' scale(-1 1)' : ''}`} d="M -16 -3 Q -3 10 16 5" />
      );
    case 'flat':
      return <path className="eye-fill" transform={transform} d="M -15 0 H 15 A 15 15 0 0 1 -15 0 Z" />;
    default:
      return <ellipse className="eye-fill" transform={transform} rx="13" ry="18" />;
  }
}

function Cheek({ x, blush, lines }: { x: number; blush: number; lines: boolean }) {
  return (
    <g transform={`translate(${x} ${EYE_Y + 24})`} style={{ opacity: blush }}>
      <ellipse className="cheek" rx="13" ry="7" />
      {lines && (
        <g className="cheek-lines">
          <path d="M -7 -2 l -3 5" />
          <path d="M -1 -2 l -3 5" />
          <path d="M 5 -2 l -3 5" />
        </g>
      )}
    </g>
  );
}

function Mouth({ shape, level }: { shape: MouthShape; level: number }) {
  const transform = 'translate(100 86)';
  switch (shape) {
    case 'open': {
      const height = 4 + Math.min(1, level) * 18;
      return <ellipse className="mouth" transform={transform} rx={11 + level * 4} ry={height / 2 + 2} />;
    }
    case 'grin':
      return <path className="mouth" transform={transform} d="M -15 -4 Q 0 18 15 -4 Z" />;
    case 'o':
      return <ellipse className="mouth" transform={transform} rx="8" ry="9" />;
    case 'small':
      return <ellipse className="mouth" transform={transform} rx="5" ry="3.2" />;
    case 'flat':
      return <path className="mouth-line" transform={transform} d="M -10 0 H 10" />;
    case 'frown':
      return <path className="mouth-line" transform={transform} d="M -12 5 Q 0 -6 12 5" />;
    default:
      return <path className="mouth-line" transform={transform} d="M -13 -3 Q 0 10 13 -3" />;
  }
}

function Sleepy() {
  return (
    <g className="sleepy">
      <text x="150" y="30">z</text>
      <text x="160" y="20">z</text>
    </g>
  );
}

function useBlink(enabled: boolean): boolean {
  const [blinking, setBlinking] = useState(false);
  useEffect(() => {
    if (!enabled) return;
    let timeout = 0;
    const schedule = () => {
      timeout = window.setTimeout(() => {
        setBlinking(true);
        timeout = window.setTimeout(() => {
          setBlinking(false);
          schedule();
        }, 140);
      }, 2500 + Math.random() * 3500);
    };
    schedule();
    return () => window.clearTimeout(timeout);
  }, [enabled]);
  return enabled && blinking;
}

function useIdleGaze(enabled: boolean): { x: number; y: number } {
  const [gaze, setGaze] = useState({ x: 0, y: 0 });
  useEffect(() => {
    if (!enabled) {
      setGaze({ x: 0, y: 0 });
      return;
    }
    const interval = window.setInterval(() => {
      setGaze(Math.random() < 0.5 ? { x: 0, y: 0 } : { x: (Math.random() - 0.5) * 12, y: (Math.random() - 0.5) * 6 });
    }, 3200);
    return () => window.clearInterval(interval);
  }, [enabled]);
  return gaze;
}
