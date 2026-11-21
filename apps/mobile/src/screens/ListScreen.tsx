import { useCallback, useState, type ReactElement } from 'react';
import { Alert, FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import { Icon } from '../components/Icons';
import { Card, ErrorText, Muted } from '../components/ui';
import { useSession } from '../session';
import { useTheme } from '../theme';

export interface ListItem {
  id: number;
  title: string;
  meta?: string;
}

interface Props<T> {
  load(): Promise<T[]>;
  toItem(value: T): ListItem;
  remove(value: T): Promise<void>;
  removeLabel: string;
  confirm: string;
  empty: string;
  header?: ReactElement;
}

/** A list from the core that can be refreshed and whose entries can be removed. */
export function ListScreen<T>({ load, toItem, remove, removeLabel, confirm, empty, header }: Props<T>) {
  const theme = useTheme();
  const { explain } = useSession();
  const [values, setValues] = useState<T[]>();
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string>();

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      setValues(await load());
      setError(undefined);
    } catch (cause) {
      setError(explain(cause));
    } finally {
      setRefreshing(false);
    }
  }, [load, explain]);

  useFocusEffect(
    useCallback(() => {
      void refresh();
    }, [refresh]),
  );
  function ask(value: T) {
    const item = toItem(value);
    Alert.alert(confirm, item.title, [
      { text: 'Abbrechen', style: 'cancel' },
      {
        text: removeLabel,
        style: 'destructive',
        onPress: () =>
          void remove(value)
            .then(refresh)
            .catch((cause: unknown) => setError(explain(cause))),
      },
    ]);
  }

  return (
    <FlatList
      style={{ backgroundColor: theme.background }}
      contentContainerStyle={styles.content}
      data={values ?? []}
      keyExtractor={(value) => String(toItem(value).id)}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => void refresh()} tintColor={theme.accent} />}
      ListHeaderComponent={
        <View style={styles.header}>
          {header}
          {error && <ErrorText>{error}</ErrorText>}
        </View>
      }
      ListEmptyComponent={values ? <Muted>{empty}</Muted> : undefined}
      renderItem={({ item: value }) => {
        const item = toItem(value);
        return (
          <Card style={styles.item}>
            <View style={styles.itemText}>
              <Text style={[styles.title, { color: theme.text }]}>{item.title}</Text>
              {item.meta && <Text style={[styles.meta, { color: theme.muted }]}>{item.meta}</Text>}
            </View>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={`${removeLabel}: ${item.title}`}
              hitSlop={10}
              onPress={() => ask(value)}
              style={[styles.remove, { backgroundColor: theme.danger }]}
            >
              <Icon name="trash" color={theme.dangerText} size={18} />
            </Pressable>
          </Card>
        );
      }}
    />
  );
}

const styles = StyleSheet.create({
  content: { padding: 16, gap: 10 },
  header: { gap: 10 },
  item: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  itemText: { flex: 1, gap: 4 },
  title: { fontSize: 16, lineHeight: 22 },
  meta: { fontSize: 13 },
  remove: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
});
