import { useRouter } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  FlatList,
  Keyboard,
  KeyboardAvoidingView,
  Text,
  View,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { useAgentStatus } from '../../lib/AgentStatus';
import { openNewChat } from '../../lib/chatRoutes';
import { haptics } from '../../lib/haptics';
import type { ChatMessage } from '../../lib/chatState';
import { useConversations } from '../../lib/Conversations';
import { useChatSession } from '../../lib/useChatSession';
import {
  MAX_CHROME_SCALE,
  MIN_TARGET,
  space,
  type,
  useTheme,
  useThemedStyles,
  type Palette,
} from '../../theme';
import { useIntro } from '../brand/LaunchIntro';
import { Spark } from '../brand/Spark';
import { Wordmark } from '../brand/Wordmark';
import { GlowBackground } from '../GlowBackground';
import {
  Body,
  Button,
  COLUMN_MAX,
  ErrorText,
  IconButton,
  Loading,
  PressableScale,
  StatusDot,
} from '../ui';
import { ScreenHeader } from '../Screen';
import { Composer } from './Composer';
import { EmptyState, type EmptyTarget } from './EmptyState';
import { AssistantMessage, UserMessage } from './Message';

const NEAR_BOTTOM_PX = 160;

const makeStyles = (p: Palette) => ({
  screen: { flex: 1 },
  who: { flexDirection: 'row' as const, alignItems: 'center' as const, gap: space.xs },
  whoText: { flex: 1, gap: 1 },
  name: { ...type.headline, color: p.text },
  statusLine: { flexDirection: 'row' as const, alignItems: 'center' as const, gap: 6 },
  statusText: { ...type.caption, color: p.textMuted },
  flex: { flex: 1 },
  list: {
    flexGrow: 1,
    width: '100%' as const,
    maxWidth: COLUMN_MAX,
    alignSelf: 'center' as const,
    paddingHorizontal: space.md,
    paddingTop: space.sm,
    paddingBottom: space.md,
    gap: space.lg,
  },
  column: { width: '100%' as const, maxWidth: COLUMN_MAX, alignSelf: 'center' as const },
  center: { gap: space.md - space.xs, paddingTop: space.lg },
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

const HEADER_SPARK = 30;

/**
 * The agent's mark at the left of the Chat header, beside the wordmark: opens More. It is also
 * where the cold-launch intro lands, so it reports its on-screen position and stays hidden until
 * the intro arrives. It never animates here; only the reply avatar shows thinking.
 */
function HeaderSpark({ onPress }: { onPress: () => void }) {
  const intro = useIntro();
  const ref = useRef<View>(null);
  const { setTarget } = intro;
  const measure = useCallback(() => {
    ref.current?.measureInWindow((x, y, width) => {
      if (width > 0) setTarget(x, y, width);
    });
  }, [setTarget]);
  return (
    <PressableScale
      accessibilityLabel="More"
      accessibilityHint="Today, files, alerts, settings and chat history"
      onPress={onPress}
      hitSlop={8}
      style={{
        width: MIN_TARGET,
        height: MIN_TARGET,
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <View
        ref={ref}
        onLayout={measure}
        collapsable={false}
        style={{ opacity: intro.active ? 0 : 1 }}
      >
        <Spark size={HEADER_SPARK} />
      </View>
    </PressableScale>
  );
}

export function ChatView({
  conversationId,
  draft = '',
}: {
  conversationId: string | null;
  /** Text placed in the composer for the owner to edit and send. */
  draft?: string;
}) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  const router = useRouter();
  const status = useAgentStatus();
  const conversations = useConversations();
  const { setActiveId, refresh, items } = conversations;
  const keyboardOpen = useKeyboardOpen();
  const list = useRef<FlatList<ChatMessage>>(null);
  const stick = useRef(true);

  const openApprovals = useCallback(() => router.navigate('/approvals'), [router]);

  const openFromEmpty = useCallback(
    (target: EmptyTarget) => {
      if (target === 'today') router.push('/today');
    },
    [router],
  );

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
      haptics.impact();
      sendTurn(text);
    },
    [sendTurn],
  );

  const conversationTitle = items.find((c) => c.id === conversationId)?.title ?? null;
  const title = conversationTitle ?? 'PersonalAi';
  // A long turn can make /health time out too; while a turn runs that is "still working", not
  // offline. Offline is shown only when /health fails with nothing in flight.
  const statusText = session.busy
    ? status.online === false
      ? 'Still working…'
      : 'Thinking…'
    : status.online === null
      ? 'Checking…'
      : status.online
        ? 'Online'
        : 'Agent offline';
  const statusColor =
    session.busy || status.online
      ? palette.ok
      : status.online === null
        ? palette.textMuted
        : palette.danger;
  const lastAssistant = [...session.messages].reverse().find((m) => m.role === 'assistant');
  const empty = session.messages.length === 0 && !session.loading && !session.loadError;

  return (
    <View style={{ flex: 1, backgroundColor: palette.bg }}>
      <GlowBackground />
      <SafeAreaView style={styles.screen} edges={['top']}>
        <View style={styles.column}>
          <ScreenHeader
            title={title}
            left={
              <View style={styles.who}>
                <HeaderSpark onPress={() => router.push('/more')} />
                <View
                  style={styles.whoText}
                  accessible
                  accessibilityLabel={`PersonalAi. ${statusText}${conversationTitle ? `. ${conversationTitle}` : ''}`}
                >
                  <Wordmark />
                  <View style={styles.statusLine}>
                    <StatusDot color={statusColor} />
                    <Text
                      style={styles.statusText}
                      numberOfLines={1}
                      maxFontSizeMultiplier={MAX_CHROME_SCALE}
                    >
                      {conversationTitle ? `${statusText} · ${conversationTitle}` : statusText}
                    </Text>
                  </View>
                </View>
              </View>
            }
            right={
              <>
                <IconButton
                  icon="clock"
                  glass
                  label="Chat history"
                  onPress={() => router.push('/history')}
                />
                {session.messages.length > 0 ? (
                  <IconButton
                    icon="edit"
                    glass
                    label="New chat"
                    onPress={() => openNewChat(router)}
                  />
                ) : null}
              </>
            }
          />
        </View>
        <KeyboardAvoidingView style={styles.flex} behavior="padding">
          <FlatList
            ref={list}
            style={styles.flex}
            contentContainerStyle={styles.list}
            data={session.messages}
            keyExtractor={(m) => m.id}
            // A tap on the message list (not on a control) or a drag puts the keyboard away.
            keyboardShouldPersistTaps="handled"
            keyboardDismissMode="on-drag"
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
                  onOpenApprovals={openApprovals}
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
                <EmptyState
                  onPick={send}
                  onOpen={openFromEmpty}
                  disabled={status.online === false || session.busy}
                />
              ) : null
            }
          />
          <View style={[styles.column, { paddingBottom: keyboardOpen ? 0 : space.xs }]}>
            <Composer
              initialDraft={draft}
              busy={session.busy}
              online={status.online}
              onSend={send}
              onStop={session.stop}
            />
          </View>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </View>
  );
}
