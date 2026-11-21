import type { ReactNode } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View, type StyleProp, type ViewStyle } from 'react-native';
import { radius, useTheme } from '../theme';

export function Card({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  const theme = useTheme();
  return (
    <View style={[styles.card, { backgroundColor: theme.card, borderColor: theme.cardBorder }, style]}>{children}</View>
  );
}

type ButtonKind = 'primary' | 'quiet' | 'danger';

export function Button({
  label,
  onPress,
  kind = 'primary',
  disabled = false,
  busy = false,
}: {
  label: string;
  onPress(): void;
  kind?: ButtonKind;
  disabled?: boolean;
  busy?: boolean;
}) {
  const theme = useTheme();
  const colors: Record<ButtonKind, { background: string; text: string }> = {
    primary: { background: theme.accent, text: theme.accentText },
    quiet: { background: theme.dark ? '#2e2737' : 'rgba(111,93,136,0.1)', text: theme.text },
    danger: { background: theme.danger, text: theme.dangerText },
  };
  const color = colors[kind];
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: disabled || busy, busy }}
      disabled={disabled || busy}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        { backgroundColor: color.background, opacity: disabled ? 0.5 : pressed ? 0.8 : 1 },
      ]}
    >
      {busy ? <ActivityIndicator color={color.text} /> : <Text style={[styles.buttonText, { color: color.text }]}>{label}</Text>}
    </Pressable>
  );
}

export function Muted({ children }: { children: ReactNode }) {
  const theme = useTheme();
  return <Text style={[styles.muted, { color: theme.muted }]}>{children}</Text>;
}

export function ErrorText({ children }: { children: ReactNode }) {
  const theme = useTheme();
  return (
    <Text accessibilityRole="alert" style={[styles.error, { color: theme.dangerText, backgroundColor: theme.danger }]}>
      {children}
    </Text>
  );
}

export function Title({ children }: { children: ReactNode }) {
  const theme = useTheme();
  return <Text style={[styles.title, { color: theme.text }]}>{children}</Text>;
}

const styles = StyleSheet.create({
  card: {
    borderRadius: radius.card,
    borderWidth: StyleSheet.hairlineWidth,
    padding: 16,
    gap: 8,
  },
  button: {
    minHeight: 46,
    paddingHorizontal: 20,
    borderRadius: radius.pill,
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonText: { fontSize: 16, fontWeight: '600' },
  muted: { fontSize: 14, lineHeight: 20 },
  error: { fontSize: 14, lineHeight: 20, padding: 12, borderRadius: 12, overflow: 'hidden' },
  title: { fontSize: 28, fontWeight: '700', letterSpacing: -0.4 },
});
