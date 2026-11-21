import { useEffect, useRef, useState } from 'react';
import {
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import * as Haptics from 'expo-haptics';
import type { AppNotification, Expression } from '@pebbo/contracts';
import { appendMessages, emotionOf, markFailed, myMessage, pebboMessage, type ChatMessage } from '../chat';
import { Face } from '../components/Face';
import { Icon } from '../components/Icons';
import { Button } from '../components/ui';
import { useSession } from '../session';
import { radius, useTheme } from '../theme';

// How long Pebbo keeps the face of its last answer.
const EMOTION_MS = 6000;

export function ChatScreen({ pending, onAcknowledge }: { pending: AppNotification[]; onAcknowledge(): void }) {
  const theme = useTheme();
  const { client, credentials, explain } = useSession();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [text, setText] = useState('');
  const [thinking, setThinking] = useState(false);
  const [expression, setExpression] = useState<Expression>('neutral');
  const [error, setError] = useState<string>();
  const list = useRef<FlatList<ChatMessage>>(null);

  useEffect(() => {
    if (expression === 'neutral' || expression === 'thinking') return;
    const timer = setTimeout(() => setExpression('neutral'), EMOTION_MS);
    return () => clearTimeout(timer);
  }, [expression]);

  async function send() {
    const message = myMessage(text);
    if (!message.text || thinking) return;
    setText('');
    setError(undefined);
    setMessages((current) => appendMessages(current, message));
    setThinking(true);
    setExpression('thinking');
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    try {
      const reply = await client.chat(message.text);
      setMessages((current) => appendMessages(current, pebboMessage(reply)));
      setExpression(emotionOf(reply));
    } catch (cause) {
      setMessages((current) => markFailed(current, message.id));
      setError(explain(cause));
      setExpression('sad');
    } finally {
      setThinking(false);
    }
  }

  return (
    <SafeAreaView edges={['top']} style={[styles.fill, { backgroundColor: theme.background }]}>
      <View style={styles.header}>
        <Face expression={expression} size={64} />
        <View style={styles.headerText}>
          <Text style={[styles.name, { color: theme.text }]}>Pebbo</Text>
          <Text style={[styles.status, { color: theme.muted }]}>
            {thinking ? 'denkt nach …' : `Hoi ${credentials.person.name}!`}
          </Text>
        </View>
      </View>

      {pending.length > 0 && (
        <View
          accessibilityRole="alert"
          style={[styles.banner, { backgroundColor: theme.card, borderColor: theme.glowStrong, shadowColor: theme.glowStrong }]}
        >
          {pending.map((notification) => (
            <Text key={notification.id} style={[styles.bannerText, { color: theme.text }]}>
              Erinnerung: {notification.text} <Text style={{ color: theme.muted }}>({notification.due_text})</Text>
            </Text>
          ))}
          <Button label="Gesehen" kind="quiet" onPress={onAcknowledge} />
        </View>
      )}

      <KeyboardAvoidingView
        style={styles.fill}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        keyboardVerticalOffset={Platform.OS === 'ios' ? 80 : 0}
      >
        <FlatList
          ref={list}
          data={messages}
          keyExtractor={(message) => message.id}
          contentContainerStyle={styles.messages}
          onContentSizeChange={() => list.current?.scrollToEnd({ animated: true })}
          ListEmptyComponent={
            <Text style={[styles.empty, { color: theme.muted }]}>
              Schreib mir etwas. Ich kann mir Sachen merken, dich an etwas erinnern oder einfach plaudern.
            </Text>
          }
          renderItem={({ item }) => <Bubble message={item} />}
        />
        {error && <Text style={[styles.error, { color: theme.dangerText }]}>{error}</Text>}
        <View style={[styles.composer, { backgroundColor: theme.card, borderColor: theme.cardBorder }]}>
          <TextInput
            accessibilityLabel="Nachricht an Pebbo"
            value={text}
            onChangeText={setText}
            placeholder="Nachricht an Pebbo"
            placeholderTextColor={theme.muted}
            multiline
            maxLength={1000}
            style={[styles.input, { color: theme.text }]}
            onSubmitEditing={() => void send()}
            submitBehavior="submit"
            returnKeyType="send"
          />
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Senden"
            disabled={!text.trim() || thinking}
            onPress={() => void send()}
            style={[styles.send, { backgroundColor: theme.accent, opacity: !text.trim() || thinking ? 0.4 : 1 }]}
          >
            <Icon name="send" color={theme.accentText} size={20} />
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function Bubble({ message }: { message: ChatMessage }) {
  const theme = useTheme();
  const mine = message.from === 'me';
  return (
    <View style={[styles.row, mine ? styles.mine : styles.theirs]}>
      {(message.text || mine) && (
        <View
          style={[
            styles.bubble,
            mine
              ? { backgroundColor: theme.myBubble, borderBottomRightRadius: 6 }
              : { backgroundColor: theme.card, borderColor: theme.cardBorder, borderWidth: StyleSheet.hairlineWidth, borderBottomLeftRadius: 6 },
          ]}
        >
          <Text style={[styles.bubbleText, { color: mine ? theme.myBubbleText : theme.text }]}>{message.text}</Text>
        </View>
      )}
      {message.failed && <Text style={[styles.failed, { color: theme.dangerText }]}>Nicht angekommen</Text>}
      {message.actions.map((action) => (
        <View key={action} style={[styles.action, { backgroundColor: theme.dark ? '#2a2333' : '#f0e6f7' }]}>
          <Icon name="check" color={theme.success} size={14} />
          <Text style={[styles.actionText, { color: theme.text }]}>{action}</Text>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  header: { flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 20, paddingVertical: 10 },
  headerText: { gap: 2 },
  name: { fontSize: 22, fontWeight: '700' },
  status: { fontSize: 14 },
  banner: {
    marginHorizontal: 16,
    padding: 14,
    gap: 8,
    borderRadius: radius.card,
    borderWidth: 1.5,
    shadowOpacity: 0.35,
    shadowRadius: 12,
    elevation: 4,
  },
  bannerText: { fontSize: 15, fontWeight: '600' },
  messages: { padding: 16, gap: 10, flexGrow: 1 },
  empty: { textAlign: 'center', marginTop: 40, paddingHorizontal: 24, fontSize: 15, lineHeight: 22 },
  row: { gap: 6, maxWidth: '85%' },
  mine: { alignSelf: 'flex-end', alignItems: 'flex-end' },
  theirs: { alignSelf: 'flex-start', alignItems: 'flex-start' },
  bubble: { paddingHorizontal: 14, paddingVertical: 10, borderRadius: radius.bubble },
  bubbleText: { fontSize: 16, lineHeight: 22 },
  failed: { fontSize: 12 },
  action: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 10, paddingVertical: 6, borderRadius: radius.pill },
  actionText: { fontSize: 13 },
  error: { paddingHorizontal: 20, paddingBottom: 6, fontSize: 14 },
  composer: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: 8,
    margin: 12,
    padding: 6,
    paddingLeft: 16,
    borderRadius: 26,
    borderWidth: StyleSheet.hairlineWidth,
  },
  input: { flex: 1, fontSize: 16, maxHeight: 120, paddingVertical: 10 },
  send: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
});
