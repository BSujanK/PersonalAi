import { Link } from 'expo-router';
import { useRef, useState } from 'react';
import {
  FlatList,
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button, colors, ErrorText } from '../../src/components/ui';
import {
  chat,
  chatStream,
  OfflineError,
  StreamUnsupportedError,
  type ChatReply,
} from '../../src/lib/api';
import { errorMessage } from '../../src/lib/format';

interface Message {
  id: number;
  from: 'me' | 'agent';
  text: string;
}

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(0);
  const conversationId = useRef<string | null>(null);
  const nextId = useRef(0);

  function append(from: Message['from'], text: string): number {
    const id = nextId.current++;
    setMessages((prev) => [...prev, { id, from, text }]);
    return id;
  }

  function setText(id: number, update: (text: string) => string) {
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, text: update(m.text) } : m)));
  }

  function remove(id: number) {
    setMessages((prev) => prev.filter((m) => m.id !== id));
  }

  function accept(id: number, result: ChatReply) {
    conversationId.current = result.conversation_id;
    setPending(result.pending_action_ids.length);
    setText(id, () => result.reply);
  }

  async function send() {
    const text = draft.trim();
    if (!text || busy) return;
    setDraft('');
    setError(null);
    setBusy(true);
    append('me', text);
    const bubble = append('agent', '');
    // Set once the server has accepted the turn (its first event), so it may already be running.
    let started = false;
    try {
      const result = await chatStream(text, conversationId.current, {
        onStart: () => {
          started = true;
        },
        onToken: (chunk) => {
          started = true;
          setText(bubble, (current) => current + chunk);
        },
        onReset: () => setText(bubble, () => ''),
      });
      accept(bubble, result);
    } catch (e) {
      // Fall back to the plain call only when the server never accepted the stream: after that it
      // may have already run the turn, so resending could repeat it.
      const canFall =
        !started && (e instanceof StreamUnsupportedError || e instanceof OfflineError);
      if (canFall) {
        try {
          accept(bubble, await chat(text, conversationId.current));
        } catch (fallbackError) {
          remove(bubble);
          setError(errorMessage(fallbackError));
        }
      } else {
        remove(bubble);
        setError(errorMessage(e));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <FlatList
          style={styles.flex}
          contentContainerStyle={styles.list}
          data={messages}
          keyExtractor={(m) => String(m.id)}
          renderItem={({ item }) => (
            <View style={[styles.bubble, item.from === 'me' ? styles.mine : styles.theirs]}>
              <Text selectable style={item.from === 'me' ? styles.mineText : styles.theirText}>
                {item.text || (item.from === 'agent' ? '…' : '')}
              </Text>
            </View>
          )}
          ListEmptyComponent={
            <Text style={styles.empty}>Ask the agent about your mail, calendar or spending.</Text>
          }
        />
        <ErrorText message={error} />
        {pending > 0 ? (
          <Link href="/approvals" style={styles.pending}>
            {pending} approval{pending === 1 ? '' : 's'} pending
          </Link>
        ) : null}
        <View style={styles.inputRow}>
          <TextInput
            style={styles.input}
            value={draft}
            onChangeText={setDraft}
            placeholder="Message"
            multiline
            editable={!busy}
          />
          <Button
            label={busy ? '...' : 'Send'}
            onPress={() => void send()}
            disabled={busy || !draft.trim()}
          />
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  flex: { flex: 1 },
  list: { padding: 16, gap: 8 },
  empty: { color: colors.muted, textAlign: 'center', marginTop: 40 },
  bubble: { maxWidth: '85%', borderRadius: 12, padding: 10 },
  mine: { alignSelf: 'flex-end', backgroundColor: colors.primary },
  theirs: {
    alignSelf: 'flex-start',
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
  },
  mineText: { color: '#ffffff', fontSize: 15 },
  theirText: { color: colors.text, fontSize: 15 },
  pending: { color: colors.primary, fontWeight: '600', paddingHorizontal: 16, paddingVertical: 6 },
  inputRow: { flexDirection: 'row', gap: 8, padding: 12, alignItems: 'flex-end' },
  input: {
    flex: 1,
    maxHeight: 120,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    padding: 10,
    backgroundColor: colors.card,
    color: colors.text,
  },
});
