import { useRouter } from 'expo-router';
import { useState } from 'react';
import { Alert, FlatList, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import type { ConversationSummary } from '../../lib/api';
import { useConversations } from '../../lib/Conversations';
import { openConversation, openNewChat } from '../../lib/chatRoutes';
import { errorMessage, rowTime } from '../../lib/format';
import { space, type, useThemedStyles, type Palette } from '../../theme';
import { GlowBackground } from '../GlowBackground';
import { ScreenHeader } from '../Screen';
import { Button, COLUMN_MAX, ListRow, SearchField } from '../ui';
import { ConversationActions } from './ConversationActions';

const makeStyles = (p: Palette) => ({
  root: { flex: 1, backgroundColor: p.bg },
  column: { width: '100%' as const, maxWidth: COLUMN_MAX, alignSelf: 'center' as const },
  top: { paddingHorizontal: space.md, gap: space.md, paddingBottom: space.sm },
  section: {
    ...type.title3,
    fontSize: 18,
    lineHeight: 24,
    color: p.text,
    paddingHorizontal: space.md + space.xs,
    paddingTop: space.sm,
    paddingBottom: space.sm + space.xs,
  },
  list: { paddingHorizontal: space.md, paddingBottom: space.xxl, gap: space.sm },
  empty: {
    ...type.subhead,
    color: p.textMuted,
    paddingHorizontal: space.md + space.xs,
    paddingVertical: space.md - space.xs,
  },
});

/**
 * Chat history: search, open, rename and delete past conversations. Reached from the Chat tab's
 * header; a conversation opens back in the Chat tab.
 */
export function ConversationList() {
  const styles = useThemedStyles(makeStyles);
  const router = useRouter();
  const conversations = useConversations();
  const [target, setTarget] = useState<ConversationSummary | null>(null);

  function newChat() {
    openNewChat(router);
  }

  function confirmDelete(item: ConversationSummary) {
    setTarget(null);
    Alert.alert('Delete chat?', `"${item.title}" will be removed from this phone and the agent.`, [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete',
        style: 'destructive',
        onPress: () => {
          void conversations.remove(item.id).then(
            () => {
              if (conversations.activeId === item.id) newChat();
            },
            (e: unknown) => Alert.alert('Could not delete', errorMessage(e)),
          );
        },
      },
    ]);
  }

  return (
    <View style={styles.root}>
      <GlowBackground />
      <SafeAreaView style={{ flex: 1 }} edges={['top', 'bottom']}>
        <View style={styles.column}>
          <ScreenHeader title="Chat history" back />
          <View style={styles.top}>
            <Button label="New chat" icon="edit" onPress={newChat} />
            <SearchField
              accessibilityLabel="Search conversations"
              placeholder="Search chats"
              value={conversations.query}
              onChangeText={conversations.setQuery}
            />
          </View>
          <Text accessibilityRole="header" style={styles.section}>
            {conversations.query.trim() ? 'Results' : 'Recents'}
          </Text>
        </View>
        <FlatList
          style={[{ flex: 1 }, styles.column]}
          contentContainerStyle={styles.list}
          data={conversations.items}
          keyExtractor={(c) => c.id}
          keyboardShouldPersistTaps="handled"
          onEndReached={conversations.loadMore}
          onEndReachedThreshold={0.5}
          renderItem={({ item }) => {
            const active = conversations.activeId === item.id;
            return (
              <ListRow
                icon="message-circle"
                title={item.title}
                subtitle={item.preview || rowTime(item.updated_at) || null}
                subtitleLines={1}
                selected={active}
                accessibilityLabel={item.title}
                accessibilityHint="Opens this chat. Long press for rename and delete."
                accessibilityActions={[
                  { name: 'rename', label: 'Rename' },
                  { name: 'delete', label: 'Delete' },
                ]}
                onAccessibilityAction={(event) => {
                  if (event.nativeEvent.actionName === 'delete') confirmDelete(item);
                  else setTarget(item);
                }}
                onPress={() => openConversation(router, item.id)}
                onLongPress={() => setTarget(item)}
              />
            );
          }}
          ListEmptyComponent={
            <Text style={styles.empty}>
              {conversations.error
                ? conversations.error
                : conversations.loading
                  ? 'Loading...'
                  : conversations.query.trim()
                    ? 'No chats match that search.'
                    : 'No chats yet. Start one above.'}
            </Text>
          }
        />
      </SafeAreaView>

      <ConversationActions
        key={target?.id ?? 'closed'}
        target={target}
        onClose={() => setTarget(null)}
        onRename={conversations.rename}
        onDelete={confirmDelete}
      />
    </View>
  );
}
