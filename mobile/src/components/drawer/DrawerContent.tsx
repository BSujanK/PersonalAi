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
  radius,
  space,
  type,
  useTheme,
  useThemedStyles,
  type Palette,
} from '../../theme';
import { Icon, type IconName } from '../Icon';
import { PressableScale, SearchField } from '../ui';
import { ConversationActions } from './ConversationActions';

const makeStyles = (p: Palette) => ({
  root: { flex: 1, backgroundColor: p.drawer },
  top: { paddingHorizontal: space.md, paddingTop: space.md - space.xs, gap: space.md - space.xs },
  brandRow: { flexDirection: 'row' as const, alignItems: 'center' as const, gap: space.sm },
  brandMark: {
    width: 28,
    height: 28,
    borderRadius: radius.sm,
    backgroundColor: p.accent,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
  },
  brand: { ...type.title2, color: p.text },
  newChat: {
    minHeight: MIN_TARGET + 4,
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    gap: space.sm + 2,
    paddingHorizontal: space.md,
    borderRadius: radius.md,
    backgroundColor: p.accent,
  },
  newChatText: { ...type.headline, color: p.accentOn },
  section: {
    ...type.footnote,
    fontFamily: fontFamily.bodySemiBold,
    letterSpacing: 0.4,
    textTransform: 'uppercase' as const,
    color: p.textMuted,
    paddingHorizontal: space.lg - space.xs,
    paddingTop: space.md,
    paddingBottom: space.xs,
  },
  list: { paddingHorizontal: space.sm, paddingBottom: space.sm },
  item: {
    minHeight: MIN_TARGET,
    justifyContent: 'center' as const,
    paddingHorizontal: space.md - space.xs,
    paddingVertical: space.sm,
    borderRadius: radius.md - 2,
  },
  itemActive: { backgroundColor: p.accentSoft },
  itemPressed: { backgroundColor: p.muted },
  itemTitle: { ...type.callout, color: p.text },
  itemTitleActive: { fontFamily: fontFamily.bodySemiBold, color: p.accentText },
  empty: {
    ...type.subhead,
    color: p.textMuted,
    paddingHorizontal: space.lg - space.xs,
    paddingVertical: space.md - space.xs,
  },
  footer: {
    borderTopWidth: 1,
    borderTopColor: p.separator,
    paddingHorizontal: space.sm,
    paddingVertical: space.sm,
  },
  link: {
    minHeight: MIN_TARGET + 4,
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    gap: space.md - space.xs,
    paddingHorizontal: space.md - space.xs,
    borderRadius: radius.md - 2,
  },
  linkText: { ...type.callout, fontFamily: fontFamily.bodyMedium, flex: 1, color: p.text },
  badge: {
    minWidth: 24,
    height: 24,
    borderRadius: 12,
    paddingHorizontal: space.sm - 1,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
    backgroundColor: p.accent,
  },
  badgeText: { ...type.caption, fontFamily: fontFamily.bodyBold, color: p.accentOn },
});

const LINKS: { route: string; path: string; label: string; icon: IconName }[] = [
  { route: 'today', path: '/today', label: 'Today', icon: 'sun' },
  { route: 'approvals', path: '/approvals', label: 'Approvals', icon: 'shield' },
  { route: 'files', path: '/files', label: 'Files', icon: 'folder' },
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
        <View style={styles.brandRow}>
          <View style={styles.brandMark}>
            <Icon name="cpu" size={16} color={palette.accentOn} />
          </View>
          <Text
            accessibilityRole="header"
            style={styles.brand}
            maxFontSizeMultiplier={MAX_CHROME_SCALE}
          >
            PersonalAi
          </Text>
        </View>
        <PressableScale accessibilityLabel="New chat" onPress={newChat} style={styles.newChat}>
          <Icon name="edit" size={18} color={palette.accentOn} />
          <Text style={styles.newChatText}>New chat</Text>
        </PressableScale>
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
              style={({ pressed }) => [
                styles.item,
                pressed && styles.itemPressed,
                active && styles.itemActive,
              ]}
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
              style={({ pressed }) => [
                styles.link,
                pressed && styles.itemPressed,
                active && styles.itemActive,
              ]}
            >
              <Icon
                name={link.icon}
                size={20}
                color={active ? palette.accentText : palette.textMuted}
              />
              <Text style={[styles.linkText, active && { color: palette.accentText }]}>
                {link.label}
              </Text>
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
