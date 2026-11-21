import type { CSSProperties } from 'react';
import { Face } from './face/Face';
import type { Expression } from './face/expressions';

export type RingMode = 'asleep' | 'idle' | 'listening' | 'thinking' | 'speaking' | 'muted';

interface RobotProps {
  expression: Expression;
  ring: RingMode;
  level: number;
  speaking: boolean;
}

/** Pebbo's body as in the concept art: pebble cap, head with screen, wings, torso and glowing base. */
export function Robot({ expression, ring, level, speaking }: RobotProps) {
  const style = { '--level': speaking ? level.toFixed(3) : '0' } as CSSProperties;
  return (
    <div className="robot" data-ring={ring} style={style}>
      <div className="robot-cap">
        <span className="cap-spark" />
        <span className="cap-spark" />
        <span className="cap-spark" />
      </div>
      <div className="robot-head">
        <div className="robot-mics" aria-hidden="true">
          <span />
          <span />
          <span />
          <span />
        </div>
        <div className="robot-screen">
          <Face expression={expression} level={level} speaking={speaking} />
        </div>
      </div>
      <div className="robot-wing robot-wing-left" />
      <div className="robot-wing robot-wing-right" />
      <div className="robot-torso">
        <div className="robot-speaker" />
      </div>
      <div className="robot-ring" />
      <div className="robot-base" />
    </div>
  );
}
