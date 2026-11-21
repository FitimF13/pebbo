import { useEffect, useState } from 'react';
import { Alert, ScrollView, StyleSheet, Text, View } from 'react-native';
import { ROLE_LABELS } from '../roles';
import { Button, Card, Muted } from '../components/ui';
import { useSession } from '../session';
import { useTheme } from '../theme';

export function SettingsScreen() {
  const theme = useTheme();
  const { client, credentials, unpair, explain } = useSession();
  const [version, setVersion] = useState<string>();
  const [status, setStatus] = useState<string>('Verbinde …');

  useEffect(() => {
    client
      .me()
      .then((me) => {
        setVersion(me.version);
        setStatus('Verbunden');
      })
      .catch((cause: unknown) => setStatus(explain(cause)));
  }, [client, explain]);

  function confirmUnpair() {
    Alert.alert('Handy entkoppeln?', 'Danach kann dieses Handy nicht mehr mit Pebbo chatten, bis du es neu koppelst.', [
      { text: 'Abbrechen', style: 'cancel' },
      { text: 'Entkoppeln', style: 'destructive', onPress: () => void unpair() },
    ]);
  }

  const rows: [string, string][] = [
    ['Person', `${credentials.person.name} (${ROLE_LABELS[credentials.person.role]})`],
    ['Dieses Handy', credentials.phoneName],
    ['Pebbo', credentials.address],
    ['Status', status],
    ...(version ? ([['Version', version]] as [string, string][]) : []),
  ];

  return (
    <ScrollView style={{ backgroundColor: theme.background }} contentContainerStyle={styles.content}>
      <Card>
        {rows.map(([label, value]) => (
          <View key={label} style={styles.row}>
            <Text style={[styles.label, { color: theme.muted }]}>{label}</Text>
            <Text style={[styles.value, { color: theme.text }]} selectable>
              {value}
            </Text>
          </View>
        ))}
      </Card>
      <Muted>
        Personen, Stimmen, Geräte und alles Weitere stellst du im Kontrollzentrum am Computer ein, auf dem Pebbo läuft.
        Die App funktioniert im Moment nur im gleichen WLAN wie Pebbo.
      </Muted>
      <Button label="Entkoppeln" kind="danger" onPress={confirmUnpair} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: { padding: 16, gap: 16 },
  row: { flexDirection: 'row', justifyContent: 'space-between', gap: 16, paddingVertical: 6 },
  label: { fontSize: 15 },
  value: { fontSize: 15, fontWeight: '600', flexShrink: 1, textAlign: 'right' },
});
