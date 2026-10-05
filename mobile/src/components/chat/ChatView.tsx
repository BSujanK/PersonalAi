import { useRouter } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  FlatList,
  Keyboard,
  KeyboardAvoidingView,
  View,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
} from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';

import { useAgentStatus } from '../../lib/AgentStatus';
import { openNewChat } from '../../lib/chatRoutes';
import type { ChatMessage } from '../../lib/chatState';
import { useConversations } from '../../lib/Conversations';
import { useChatSession } from '../../lib/useChatSession';
import { useThemedStyles, type Palette } from '../../theme';
import { Body, Button, COLUMN_MAX, ErrorText, IconButton, Loading } from '../ui';
import { ScreenHeader } from '../Screen';
import { Composer } from './Composer';
import { EmptyState } from './EmptyState';
import { AssistantMessage, UserMessage } from './Message';

const NEAR_BOTTOM_PX = 160;

const makeStyles = (p: Palette) => ({
  screen: { flex: 1, backgroundColor: p.bg },
  flex: { flex: 1 },
  list: {
    flexGrow: 1,
    width: '100%' as const,
    maxWidth: COLUMN_MAX,
    alignSelf: 'center' as const,
    paddingHorizontal: 16,
    paddingTop: 8,
    paddingBottom: 16,
    gap: 22,
  },
  column: { width: '100%' as const, maxWidth: COLUMN_MAX, alignSelf: 'center' as const },
  center: { gap: 12, paddingTop: 24 },
});

/** The keyboard hides the system bar, so the bottom inset must not add a gap above it. */
function useKeyboardOpen(): boolean {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const show = Keyboard.addListener('keyboardDidShow', () => setOpen(true));
    const hide = Keyboard.addListener('keyboardDidHide', () => setOpen(false));
    return () => {
      show.remove();
      hide.remove();
    };
  }, []);
  return open;
}

export function ChatView({ conversationId }: { conversationId: string | null }) {
  const styles = useThemedStyles(makeStyles);
  const router = useRouter();
  const status = useAgentStatus();
  const conversations = useConversations();
  const { setActiveId, refresh, items } = conversations;
  const insets = useSafeAreaInsets();
  const keyboardOpen = useKeyboardOpen();
  const list = useRef<FlatList<ChatMessage>>(null);
  const stick = useRef(true);

  const session = useChatSession({
    initialId: conversationId,
    onConversation: setActiveId,
    onTurnEnd: () => {
      refresh();
      status.refresh();
    },
  });

  useEffect(() => {
    setActiveId(conversationId);
  }, [conversationId, setActiveId]);

  const onScroll = useCallback((event: NativeSyntheticEvent<NativeScrollEvent>) => {
    const { contentOffset, contentSize, layoutMeasurement } = event.nativeEvent;
    stick.current =
      contentSize.height - (contentOffset.y + layoutMeasurement.height) < NEAR_BOTTOM_PX;
  }, []);

  const { send: sendTurn } = session;
  const send = useCallback(
    (text: string) => {
      stick.current = true;
      sendTurn(text);
    },
    [sendTurn],
  );

  const title = items.find((c) => c.id === conversationId)?.title ?? 'PersonalAi';
  const lastAssistant = [...session.messages].reverse().find((m) => m.role === 'assistant');
  const empty = session.messages.length === 0 && !session.loading && !session.loadError;

  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      <ScreenHeader
        title={title}
        menu
        right={
          session.messages.length > 0 ? (
            <IconButton icon="edit" label="New chat" onPress={() => openNewChat(router)} />
          ) : null
        }
      />
      <KeyboardAvoidingView style={styles.flex} behavior="padding">
        <FlatList
          ref={list}
          style={styles.flex}
          contentContainerStyle={styles.list}
          data={session.messages}
          keyExtractor={(m) => m.id}
          keyboardShouldPersistTaps="handled"
          onScroll={onScroll}
          scrollEventThrottle={64}
          onContentSizeChange={() => {
            if (stick.current) list.current?.scrollToEnd({ animated: false });
          }}
          renderItem={({ item }) =>
            item.role === 'user' ? (
              <UserMessage message={item} />
            ) : (
              <AssistantMessage
                message={item}
                canRetry={!session.busy && item.id === lastAssistant?.id}
                onRetry={session.retry}
              />
            )
          }
          ListHeaderComponent={
            session.loading ? (
              <Loading />
            ) : session.loadError ? (
              <View style={styles.center}>
                <ErrorText message={session.loadError} />
                <Body muted>Could not open this conversation.</Body>
                <Button label="Try again" tone="plain" onPress={session.reload} />
              </View>
            ) : null
          }
          ListEmptyComponent={
            empty ? (
              <EmptyState onPick={send} disabled={status.online === false || session.busy} />
            ) : null
          }
        />
        <View style={[styles.column, { paddingBottom: keyboardOpen ? 0 : insets.bottom }]}>
          <Composer
            busy={session.busy}
            online={status.online}
            onSend={send}
            onStop={session.stop}
          />
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
