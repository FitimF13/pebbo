import Svg, { Circle, Path } from 'react-native-svg';

export type IconName = 'chat' | 'bell' | 'memory' | 'settings' | 'send' | 'check' | 'trash';

const PATHS: Record<IconName, string[]> = {
  chat: ['M4 5h16v11H9l-5 4z'],
  bell: ['M6 17V11a6 6 0 0 1 12 0v6l1.5 2h-15z', 'M10 21h4'],
  memory: ['M12 3l2.6 5.4 5.9.8-4.3 4.1 1 5.9L12 16.4 6.8 19.2l1-5.9-4.3-4.1 5.9-.8z'],
  settings: ['M4 7h10', 'M18 7h2', 'M4 17h2', 'M10 17h10'],
  send: ['M5 12h13', 'M12 5l7 7-7 7'],
  check: ['M5 12.5l4.5 4.5L19 7.5'],
  trash: ['M5 7h14', 'M10 7V5h4v2', 'M7 7l1 13h8l1-13'],
};

/** Simple line icons, drawn locally. */
export function Icon({ name, color, size = 24 }: { name: IconName; color: string; size?: number }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      {PATHS[name].map((d) => (
        <Path key={d} d={d} />
      ))}
      {name === 'settings' && (
        <>
          <Circle cx={16} cy={7} r={2} />
          <Circle cx={8} cy={17} r={2} />
        </>
      )}
    </Svg>
  );
}
