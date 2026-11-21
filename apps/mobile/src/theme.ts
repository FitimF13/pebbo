/** Pebbo's palette from the concept: cream, lavender and a warm glow, in light and dark. */
import { useColorScheme } from 'react-native';

export interface Theme {
  dark: boolean;
  background: string;
  card: string;
  cardBorder: string;
  text: string;
  muted: string;
  accent: string;
  accentText: string;
  myBubble: string;
  myBubbleText: string;
  glow: string;
  glowStrong: string;
  screen: string;
  danger: string;
  dangerText: string;
  success: string;
}

const light: Theme = {
  dark: false,
  background: '#f4ebe1',
  card: '#fffaf4',
  cardBorder: '#e6d8c8',
  text: '#3b3142',
  muted: '#7d7088',
  accent: '#6f5d88',
  accentText: '#ffffff',
  myBubble: '#8e7ba6',
  myBubbleText: '#ffffff',
  glow: '#ffd9a8',
  glowStrong: '#ffb36b',
  screen: '#17131c',
  danger: '#ffe4e4',
  dangerText: '#8a2c2c',
  success: '#1f7a4d',
};

const dark: Theme = {
  dark: true,
  background: '#121016',
  card: '#1f1a26',
  cardBorder: '#2e2737',
  text: '#f4ebe1',
  muted: '#a99bb5',
  accent: '#b9a6d3',
  accentText: '#17131c',
  myBubble: '#6f5d88',
  myBubbleText: '#ffffff',
  glow: '#ffd9a8',
  glowStrong: '#ffb36b',
  screen: '#0b090e',
  danger: '#3a1f24',
  dangerText: '#ffb4b4',
  success: '#6fd7a3',
};

export function useTheme(): Theme {
  return useColorScheme() === 'dark' ? dark : light;
}

export const radius = { card: 18, bubble: 20, pill: 999 };
