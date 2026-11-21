import { useEffect, useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import * as Haptics from 'expo-haptics';
import type { PairingTarget } from '@pebbo/contracts';
import { Face } from '../components/Face';
import { Button, Card, ErrorText, Muted, Title } from '../components/ui';
import { DEFAULT_PHONE_NAME, pairPhone, type Credentials } from '../pairing';
import { secureCredentials } from '../storage';
import { radius, useTheme } from '../theme';

interface Props {
  /** Address and code from a scanned QR code. */
  target: PairingTarget | undefined;
  /** Why the app is back at pairing, for example because the phone was removed. */
  notice: string | undefined;
  onPaired(credentials: Credentials): void;
}

export function PairingScreen({ target, notice, onPaired }: Props) {
  const theme = useTheme();
  const [address, setAddress] = useState(target?.address ?? '');
  const [code, setCode] = useState(target?.code ?? '');
  const [name, setName] = useState(DEFAULT_PHONE_NAME);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  useEffect(() => {
    if (!target) return;
    setAddress(target.address);
    setCode(target.code);
  }, [target]);

  async function submit() {
    setBusy(true);
    setError(undefined);
    try {
      const credentials = await pairPhone({ address, code, name }, { fetch, store: secureCredentials });
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      onPaired(credentials);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Das Koppeln hat nicht geklappt.');
      setBusy(false);
    }
  }

  const input = [styles.input, { color: theme.text, backgroundColor: theme.background, borderColor: theme.cardBorder }];

  return (
    <SafeAreaView style={[styles.fill, { backgroundColor: theme.background }]}>
      <KeyboardAvoidingView style={styles.fill} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <View style={styles.hero}>
            <Face expression={target ? 'happy' : 'curious'} size={150} />
            <Title>Hoi! Ich bin Pebbo.</Title>
            <Muted>
              Koppel dein Handy mit deinem Pebbo zu Hause. Öffne dafür am Computer das Kontrollzentrum, geh zu «Geräte»
              und erstelle unter «Handys» einen Code für dich.
            </Muted>
          </View>
          {notice && <ErrorText>{notice}</ErrorText>}
          <Card>
            <Text style={[styles.label, { color: theme.muted }]}>
              {target
                ? 'Der QR-Code ist gelesen. Prüf den Namen und tipp auf «Koppeln».'
                : 'Scanne den QR-Code mit der Kamera-App, oder gib Adresse und Code hier ein.'}
            </Text>
            <Text style={[styles.label, { color: theme.text }]}>Adresse von Pebbo</Text>
            <TextInput
              accessibilityLabel="Adresse von Pebbo"
              value={address}
              onChangeText={setAddress}
              placeholder="192.168.1.20"
              placeholderTextColor={theme.muted}
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="url"
              style={input}
            />
            <Text style={[styles.label, { color: theme.text }]}>Code</Text>
            <TextInput
              accessibilityLabel="Code"
              value={code}
              onChangeText={(value) => setCode(value.replace(/\D/g, '').slice(0, 6))}
              placeholder="123456"
              placeholderTextColor={theme.muted}
              keyboardType="number-pad"
              textContentType="oneTimeCode"
              maxLength={6}
              style={[input, styles.code]}
            />
            <Text style={[styles.label, { color: theme.text }]}>Name dieses Handys</Text>
            <TextInput
              accessibilityLabel="Name dieses Handys"
              value={name}
              onChangeText={setName}
              maxLength={40}
              style={input}
            />
            {error && <ErrorText>{error}</ErrorText>}
            <Button label="Koppeln" onPress={() => void submit()} busy={busy} disabled={!address.trim() || code.length !== 6} />
          </Card>
          <Muted>
            Pebbo läuft bei dir zu Hause. Das Handy spricht nur mit deinem Pebbo, nie mit einem fremden Server.
          </Muted>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  content: { padding: 20, gap: 18 },
  hero: { alignItems: 'center', gap: 12, paddingTop: 16 },
  label: { fontSize: 14, fontWeight: '600' },
  input: {
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.card / 1.5,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 17,
  },
  code: { letterSpacing: 6, fontSize: 22, fontVariant: ['tabular-nums'] },
});
