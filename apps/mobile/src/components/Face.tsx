import { useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import Svg, { Ellipse, G, Path } from 'react-native-svg';
import { FACES, type EyeShape, type Expression, type MouthShape } from '@pebbo/contracts';
import { useTheme } from '../theme';

const EYE_X = 60;
const EYE_Y = 50;
const LIGHT = '#fff3e3';
const MOUTH = '#ff9fa8';
const CHEEK = '#ff8fa3';

/** Pebbo's glowing screen face, drawn from the same parameters as on the PC and the body. */
export function Face({ expression, size = 96 }: { expression: Expression; size?: number }) {
  const theme = useTheme();
  const face = FACES[expression];
  const blinking = useBlink(face.eyes === 'open');
  const eyes = blinking ? 'closed' : face.eyes;
  const height = (size * 120) / 200;

  return (
    <View
      accessible
      accessibilityRole="image"
      accessibilityLabel={`Pebbo: ${expression}`}
      style={[
        styles.screen,
        { width: size, height, backgroundColor: theme.screen, shadowColor: theme.glowStrong, borderRadius: size / 4 },
      ]}
    >
      <Svg width={size} height={height} viewBox="0 0 200 120">
        <G x={face.gaze.x} y={face.gaze.y}>
          <Eye x={EYE_X} shape={eyes} scale={face.eyeScale} />
          <Eye x={200 - EYE_X} shape={eyes} scale={face.eyeScale} mirrored />
          <Cheek x={EYE_X - 20} blush={face.blush} lines={face.blushLines} />
          <Cheek x={200 - EYE_X + 20} blush={face.blush} lines={face.blushLines} />
          <Mouth shape={face.mouth} />
        </G>
      </Svg>
    </View>
  );
}

function Eye({ x, shape, scale, mirrored = false }: { x: number; shape: EyeShape; scale: number; mirrored?: boolean }) {
  const line = { fill: 'none', stroke: LIGHT, strokeWidth: 6, strokeLinecap: 'round' as const };
  return (
    <G x={x} y={EYE_Y} scale={scale}>
      {shape === 'happy' && <Path {...line} d="M -17 7 Q 0 -17 17 7" />}
      {shape === 'closed' && <Path {...line} d="M -16 0 Q 0 12 16 0" />}
      {shape === 'sad' && <Path {...line} d={mirrored ? 'M 16 -3 Q 3 10 -16 5' : 'M -16 -3 Q -3 10 16 5'} />}
      {shape === 'flat' && <Path fill={LIGHT} d="M -15 0 H 15 A 15 15 0 0 1 -15 0 Z" />}
      {shape === 'open' && <Ellipse fill={LIGHT} rx={13} ry={18} />}
    </G>
  );
}

function Cheek({ x, blush, lines }: { x: number; blush: number; lines: boolean }) {
  return (
    <G x={x} y={EYE_Y + 24} opacity={blush}>
      <Ellipse fill={CHEEK} opacity={0.55} rx={13} ry={7} />
      {lines &&
        [-7, -1, 5].map((offset) => (
          <Path key={offset} stroke="#ffb3c1" strokeWidth={1.6} strokeLinecap="round" d={`M ${offset} -2 l -3 5`} />
        ))}
    </G>
  );
}

function Mouth({ shape }: { shape: MouthShape }) {
  const line = { fill: 'none', stroke: LIGHT, strokeWidth: 6, strokeLinecap: 'round' as const };
  switch (shape) {
    case 'open':
      return <Ellipse x={100} y={86} fill={MOUTH} rx={12} ry={8} />;
    case 'grin':
      return <Path x={100} y={86} fill={MOUTH} d="M -15 -4 Q 0 18 15 -4 Z" />;
    case 'o':
      return <Ellipse x={100} y={86} fill={MOUTH} rx={8} ry={9} />;
    case 'small':
      return <Ellipse x={100} y={86} fill={MOUTH} rx={5} ry={3.2} />;
    case 'flat':
      return <Path x={100} y={86} {...line} d="M -10 0 H 10" />;
    case 'frown':
      return <Path x={100} y={86} {...line} d="M -12 5 Q 0 -6 12 5" />;
    default:
      return <Path x={100} y={86} {...line} d="M -13 -3 Q 0 10 13 -3" />;
  }
}

function useBlink(enabled: boolean): boolean {
  const [blinking, setBlinking] = useState(false);
  useEffect(() => {
    if (!enabled) return;
    let timer: ReturnType<typeof setTimeout>;
    const schedule = () => {
      timer = setTimeout(() => {
        setBlinking(true);
        timer = setTimeout(() => {
          setBlinking(false);
          schedule();
        }, 140);
      }, 2500 + Math.random() * 3500);
    };
    schedule();
    return () => clearTimeout(timer);
  }, [enabled]);
  return enabled && blinking;
}

const styles = StyleSheet.create({
  screen: {
    overflow: 'hidden',
    shadowOpacity: 0.45,
    shadowRadius: 14,
    shadowOffset: { width: 0, height: 4 },
    elevation: 6,
  },
});
