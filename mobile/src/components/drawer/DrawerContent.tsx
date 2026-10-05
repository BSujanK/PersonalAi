import { useRouter } from 'expo-router';
import type { DrawerContentComponentProps } from 'expo-router/drawer';
import { useState } from 'react';
import { Alert, FlatList, Pressable, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { useAgentStatus } from '../../lib/AgentStatus';
import type { ConversationSummary } from '../../lib/api';
import { useConversations } from '../../lib/Conversations';
import { openConversation, openNewChat } from '../../lib/chatRoutes';
import { errorMessage } from '../../lib/format';
import {
  fontFamily,
  MAX_CHROME_SCALE,
  MIN_TARGET,
  size,
  useTheme,
  useThemedStyles,
  type Palette,
} from '../../theme';
import { Icon, type IconName } from '../Icon';
import { TextField } from '../ui';
import { ConversationActions } from './ConversationActions';

const makeStyles = (p: Palette) => ({
  root: { flex: 1, backgroundColor: p.drawer },
  top: { paddingHorizontal: 16, paddingTop: 12, gap: 12 },
  brand: { fontFamily: fontFamily.display, fontSize: size.title, color: p.text },
  newChat: {
    minHeight: MIN_TARGET + 4,
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    gap: 10,
    paddingHorizontal: 16,
    borderRadius: 26,
    backgroundColor: p.accent,
  },
  newChatText: { fontFamily: fontFamily.bodySemiBold, fontSize: size.body, color: p.accentOn },
  searchWrap: { justifyContent: 'center' as const },
  search: { paddingLeft: 40, borderRadius: 24 },
  searchIcon: { position: 'absolute' as const, left: 14 },
  section: {
    fontFamily: fontFamily.bodySemiBold,
    fontSize: size.small,
    letterSpacing: 0.4,
    textTransform: 'uppercase' as const,
    color: p.textMuted,
    paddingHorizontal: 20,
    paddingTop: 14,
    paddingBottom: 4,
  },
  list: { paddingHorizontal: 8, paddingBottom: 8 },
  item: {
    minHeight: MIN_TARGET,
    justifyContent: 'center' as const,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 12,
  },
  itemActive: { backgroundColor: p.muted },
  itemPressed: { backgroundColor: p.muted },
  itemTitle: { fontFamily: fontFamily.body, fontSize: size.body - 1, color: p.text },
  itemTitleActive: { fontFamily: fontFamily.bodyMedium },
  empty: {
    fontFamily: fontFamily.body,
    fontSize: size.small + 1,
    color: p.textMuted,
    paddingHorizontal: 20,
    paddingVertical: 12,
  },
  footer: {
    borderTopWidth: 1,
    borderTopColor: p.border,
    paddingHorizontal: 8,
    paddingVertical: 8,
  },
  link: {
    minHeight: MIN_TARGET + 4,
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    gap: 14,
    paddingHorizontal: 12,
    borderRadius: 12,
  },
  linkText: { flex: 1, fontFamily: fontFamily.bodyMedium, fontSize: size.body, color: p.text },
  badge: {
    minWidth: 24,
    height: 24,
    borderRadius: 12,
    paddingHorizontal: 7,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
    backgroundColor: p.accent,
  },
  badgeText: { fontFamily: fontFamily.bodySemiBold, fontSize: size.caption, color: p.accentOn },
});

const LINKS: { route: string; path: string; label: string; icon: IconName }[] = [
  { route: 'today', path: '/today', label: 'Today', icon: 'sun' },
  { route: 'approvals', path: '/approvals', label: 'Approvals', icon: 'shield' },
  { route: 'money', path: '/money', label: 'Money', icon: 'credit-card' },
  { route: 'settings', path: '/settings', label: 'Settings', icon: 'settings' },
];

export function AppDrawerContent({ navigation, state }: DrawerContentComponentProps) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  const router = useRouter();
  const { pendingCount } = useAgentStatus();
  const conversations = useConversations();
  const [target, setTarget] = useState<ConversationSummary | null>(null);
  const current = state.routes[state.index]?.name;

  const close = () => navigation.closeDrawer();

  function newChat() {
    openNewChat(router);
    close();
  }

  function open(item: ConversationSummary) {
    if (current === 'index' && conversations.activeId === item.id) {
      close();
      return;
    }
    openConversation(router, item.id);
    close();
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
    <SafeAreaView style={styles.root} edges={['top', 'bottom']}>
      <View style={styles.top}>
        <Text
          accessibilityRole="header"
          style={styles.brand}
          maxFontSizeMultiplier={MAX_CHROME_SCALE}
        >
          PersonalAi
        </Text>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="New chat"
          onPress={newChat}
          style={({ pressed }) => [styles.newChat, pressed && { opacity: 0.85 }]}
        >
          <Icon name="plus" size={20} color={palette.accentOn} />
          <Text style={styles.newChatText}>New chat</Text>
        </Pressable>
        <View style={styles.searchWrap}>
          <TextField
            accessibilityLabel="Search conversations"
            placeholder="Search chats"
            value={conversations.query}
            onChangeText={conversations.setQuery}
            autoCapitalize="none"
            autoCorrect={false}
            returnKeyType="search"
            style={styles.search}
          />
          <View style={styles.searchIcon} pointerEvents="none">
            <Icon name="search" size={18} color={palette.textMuted} />
          </View>
        </View>
      </View>

      <Text accessibilityRole="header" style={styles.section}>
        {conversations.query.trim() ? 'Results' : 'Recents'}
      </Text>
      <FlatList
        style={{ flex: 1 }}
        contentContainerStyle={styles.list}
        data={conversations.items}
        keyExtractor={(c) => c.id}
        keyboardShouldPersistTaps="handled"
        onEndReached={conversations.loadMore}
        onEndReachedThreshold={0.5}
        renderItem={({ item }) => {
          const active = current === 'index' && conversations.activeId === item.id;
          return (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={item.title}
              accessibilityHint="Opens this chat. Long press for rename and delete."
              accessibilityState={{ selected: active }}
              accessibilityActions={[
                { name: 'rename', label: 'Rename' },
                { name: 'delete', label: 'Delete' },
              ]}
              onAccessibilityAction={(event) => {
                if (event.nativeEvent.actionName === 'delete') confirmDelete(item);
                else setTarget(item);
              }}
              onPress={() => open(item)}
              onLongPress={() => setTarget(item)}
              delayLongPress={350}
              style={({ pressed }) => [styles.item, (active || pressed) && styles.itemActive]}
            >
              <Text numberOfLines={1} style={[styles.itemTitle, active && styles.itemTitleActive]}>
                {item.title}
              </Text>
            </Pressable>
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

      <View style={styles.footer}>
        {LINKS.map((link) => {
          const active = current === link.route;
          const badge = link.route === 'approvals' && pendingCount > 0 ? pendingCount : 0;
          return (
            <Pressable
              key={link.route}
              accessibilityRole="button"
              accessibilityLabel={badge ? `${link.label}, ${badge} pending` : link.label}
              accessibilityState={{ selected: active }}
              onPress={() => {
                router.navigate(link.path);
                close();
              }}
              style={({ pressed }) => [styles.link, (active || pressed) && styles.itemActive]}
            >
              <Icon name={link.icon} size={20} />
              <Text style={styles.linkText}>{link.label}</Text>
              {badge ? (
                <View style={styles.badge}>
                  <Text style={styles.badgeText}>{badge > 99 ? '99+' : badge}</Text>
                </View>
              ) : null}
            </Pressable>
          );
        })}
      </View>

      <ConversationActions
        key={target?.id ?? 'closed'}
        target={target}
        onClose={() => setTarget(null)}
        onRename={conversations.rename}
        onDelete={confirmDelete}
      />
    </SafeAreaView>
  );
}
