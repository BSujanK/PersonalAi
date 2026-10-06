import { useRouter } from 'expo-router';
import { useCallback, useMemo, useRef, useState } from 'react';
import { Text, View } from 'react-native';
import type Animated from 'react-native-reanimated';

import { SparkAvatar } from '../../src/components/brand/Spark';
import { Hero, type Delta } from '../../src/components/Hero';
import { QuickAccess, type QuickItem } from '../../src/components/QuickAccess';
import { Screen } from '../../src/components/Screen';
import {
  Badge,
  Button,
  EmptyRow,
  ErrorText,
  IconButton,
  ListRow,
  ListSection,
  Loading,
  StatusDot,
} from '../../src/components/ui';
import { askAboutDeadline, askAboutEvent } from '../../src/lib/agentPrompts';
import { useAgentStatus } from '../../src/lib/AgentStatus';
import {
  ApiError,
  getBalances,
  getDeadlines,
  getInbox,
  getSummary,
  getToday,
  type DigestItem,
  type InboxCategory,
  type InboxItem,
  type Today,
  type UpcomingDeadline,
} from '../../src/lib/api';
import { openNewChat } from '../../src/lib/chatRoutes';
import {
  dueLabel,
  errorMessage,
  formatInr,
  initials,
  rowTime,
  shortDateTime,
} from '../../src/lib/format';
import { greeting } from '../../src/lib/greeting';
import { appendPage, groupInbox, mailKey } from '../../src/lib/inbox';
import { usePairing } from '../../src/lib/PairingContext';
import { usePolling } from '../../src/lib/usePolling';
import {
  fontFamily,
  MAX_CHROME_SCALE,
  space,
  type,
  useTheme,
  useThemedStyles,
  type Palette,
} from '../../src/theme';

const INBOX_PAGE = 50;
const DEADLINE_DAYS = 7;
const NOT_CONFIGURED = 'Not configured on the laptop yet.';
const AVATAR = 40;

const makeStyles = (p: Palette) => ({
  who: { flexDirection: 'row' as const, alignItems: 'center' as const, gap: space.sm + space.xs },
  whoText: { flex: 1, gap: 1 },
  name: { ...type.headline, color: p.text },
  idLine: { flexDirection: 'row' as const, alignItems: 'center' as const, gap: 6 },
  id: { ...type.caption, color: p.textMuted, letterSpacing: 0.4 },
  pills: { flexDirection: 'row' as const, gap: space.sm + space.xs },
  pill: { flex: 1 },
  count: {
    minWidth: 22,
    height: 22,
    borderRadius: 11,
    paddingHorizontal: 6,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
    backgroundColor: p.accentOn,
  },
  countText: { ...type.caption, fontFamily: fontFamily.bodyBold, color: p.accentStrong },
  avatar: {
    width: AVATAR,
    height: AVATAR,
    borderRadius: AVATAR / 2,
    backgroundColor: p.accentSoft,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
  },
  avatarText: { ...type.subhead, fontFamily: fontFamily.bodySemiBold, color: p.accentText },
});

interface Inbox {
  items: InboxItem[];
  counts: Record<InboxCategory, number>;
  next: string | null;
  /** Pages loaded by "Load more", beyond the first. */
  extraPages: number;
}

interface Money {
  label: string;
  amount: number;
  delta: Delta | null;
}

/** Today's spend against yesterday's; falls back to the total balance, then to nothing. */
async function loadMoney(): Promise<Money | null> {
  try {
    const [today, yesterday] = await Promise.all([getSummary('today'), getSummary('yesterday')]);
    const spent = Math.round(Number(today.spent_inr) || 0);
    const before = Math.round(Number(yesterday.spent_inr) || 0);
    const diff = spent - before;
    const delta: Delta =
      diff === 0
        ? { text: 'Same as yesterday', direction: 'flat' }
        : {
            text: `${formatInr(String(Math.abs(diff)))} ${diff > 0 ? 'more' : 'less'} than yesterday`,
            direction: diff > 0 ? 'up' : 'down',
            // Spending less than yesterday is the good news.
            good: diff < 0,
          };
    return { label: 'Spent today', amount: spent, delta };
  } catch {
    try {
      const { accounts } = await getBalances();
      if (accounts.length === 0) return null;
      const total = accounts.reduce((sum, a) => sum + (Number(a.balance_inr) || 0), 0);
      return {
        label: 'Total balance',
        amount: Math.round(total),
        delta: {
          text: `Across ${accounts.length} account${accounts.length === 1 ? '' : 's'}`,
          direction: 'flat',
        },
      };
    } catch {
      return null;
    }
  }
}

function MailAvatar({ name }: { name: string }) {
  const styles = useThemedStyles(makeStyles);
  return (
    <View style={styles.avatar}>
      <Text style={styles.avatarText} maxFontSizeMultiplier={1.3}>
        {initials(name)}
      </Text>
    </View>
  );
}

function MailRow({
  mail,
  unread,
  onPress,
}: {
  mail: DigestItem | InboxItem;
  unread?: boolean;
  onPress: () => void;
}) {
  const { palette } = useTheme();
  const sender = mail.from_name || mail.from_addr;
  const time = rowTime(mail.received);
  return (
    <ListRow
      leading={<MailAvatar name={sender} />}
      title={sender}
      subtitle={mail.subject || '(no subject)'}
      subtitleLines={1}
      value={time || null}
      valueMuted
      dot={unread ? palette.accent : undefined}
      onPress={onPress}
      accessibilityLabel={`${unread ? 'Unread mail' : 'Mail'} from ${sender}: ${mail.subject}. ${time}`}
      accessibilityHint="Opens the full message"
    >
      {mail.reason ? <Badge label={mail.reason} tone="accent" /> : null}
    </ListRow>
  );
}

export default function HomeScreen() {
  const styles = useThemedStyles(makeStyles);
  const router = useRouter();
  const { palette } = useTheme();
  const { pairing } = usePairing();
  const status = useAgentStatus();
  const scroll = useRef<Animated.ScrollView>(null);
  const offsets = useRef<Record<'mail' | 'events', number>>({ mail: 0, events: 0 });
  const [today, setToday] = useState<Today | null>(null);
  const [money, setMoney] = useState<Money | null | undefined>(undefined);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // null until loaded, or when the agent has no /deadlines (then today's own list is shown).
  const [upcoming, setUpcoming] = useState<UpcomingDeadline[] | null>(null);
  const [inbox, setInbox] = useState<Inbox | null>(null);
  const [inboxError, setInboxError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  const load = useCallback(async () => {
    void loadMoney().then(setMoney);
    try {
      setToday(await getToday());
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError && e.status === 404 ? NOT_CONFIGURED : errorMessage(e));
    }
    getDeadlines(DEADLINE_DAYS).then(
      (r) => setUpcoming(r.items.filter((d) => d.status === 'active')),
      () => setUpcoming(null),
    );
    getInbox({ limit: INBOX_PAGE }).then(
      (page) => {
        setInboxError(null);
        // A refresh keeps pages the owner already loaded, and their "Load more" position.
        setInbox((prev) =>
          prev && prev.extraPages > 0
            ? { ...prev, items: appendPage(page.items, prev.items), counts: page.counts }
            : { items: page.items, counts: page.counts, next: page.next_cursor, extraPages: 0 },
        );
      },
      (e: unknown) =>
        setInboxError(e instanceof ApiError && e.status === 404 ? null : errorMessage(e)),
    );
  }, []);

  async function loadMore() {
    if (!inbox?.next || loadingMore) return;
    setLoadingMore(true);
    try {
      const page = await getInbox({ cursor: inbox.next, limit: INBOX_PAGE });
      setInbox({
        items: appendPage(inbox.items, page.items),
        counts: page.counts,
        next: page.next_cursor,
        extraPages: inbox.extraPages + 1,
      });
      setInboxError(null);
    } catch (e) {
      setInboxError(errorMessage(e));
    } finally {
      setLoadingMore(false);
    }
  }

  usePolling(load);

  async function refresh() {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }

  const important = useMemo(() => today?.mail?.important ?? [], [today]);
  const groups = useMemo(
    () => groupInbox(inbox?.items ?? [], inbox?.counts ?? {}, new Set(important.map(mailKey))),
    [inbox, important],
  );
  const unread = inbox?.items.filter((m) => m.unread).length ?? 0;
  const deadlineCount = upcoming?.length ?? today?.deadlines?.length ?? 0;
  const openMail = (mail: { account: string; id: string }) =>
    router.push({
      pathname: '/mail/[account]/[id]',
      params: { account: mail.account, id: mail.id },
    });
  const scrollTo = (key: 'mail' | 'events') =>
    scroll.current?.scrollTo({ y: Math.max(0, offsets.current[key] - space.md), animated: true });

  const quick: QuickItem[] = [
    {
      key: 'mail',
      icon: 'mail',
      title: 'Mail',
      detail: inbox ? `${unread} unread` : 'Inbox',
      onPress: () => scrollTo('mail'),
      accessibilityHint: 'Scrolls to all mail',
    },
    {
      key: 'calendar',
      icon: 'calendar',
      title: 'Calendar',
      detail: today?.events ? `${today.events.length} today` : 'Events',
      onPress: () => scrollTo('events'),
      accessibilityHint: 'Scrolls to today’s events',
    },
    {
      key: 'money',
      icon: 'credit-card',
      title: 'Money',
      detail: money ? formatInr(String(money.amount)) : 'Spending',
      onPress: () => router.navigate('/money'),
    },
    {
      key: 'files',
      icon: 'folder',
      title: 'Files',
      detail: 'Laptop · Drive',
      onPress: () => router.push('/files'),
    },
    {
      key: 'news',
      icon: 'globe',
      title: 'News',
      detail: 'Headlines',
      onPress: () => openNewChat(router, "What are today's top news headlines?"),
      accessibilityHint: 'Starts a chat asking for the news. You send it.',
    },
  ];

  const deviceId = pairing?.deviceId.slice(0, 8).toUpperCase() ?? '';
  const statusColor =
    status.online === null ? palette.textMuted : status.online ? palette.ok : palette.danger;

  return (
    <Screen
      tabs
      scrollRef={scroll}
      refreshing={refreshing}
      onRefresh={() => void refresh()}
      header={
        <View
          style={styles.who}
          accessible
          accessibilityLabel={`${greeting()}. Device ${deviceId}. Agent ${status.online ? 'online' : status.online === false ? 'offline' : 'checking'}.`}
        >
          <SparkAvatar size={44} />
          <View style={styles.whoText}>
            <Text style={styles.name} maxFontSizeMultiplier={MAX_CHROME_SCALE} numberOfLines={1}>
              {greeting()}
            </Text>
            <View style={styles.idLine}>
              <StatusDot color={statusColor} />
              <Text style={styles.id} maxFontSizeMultiplier={MAX_CHROME_SCALE} numberOfLines={1}>
                ID {deviceId}
              </Text>
            </View>
          </View>
        </View>
      }
      right={
        <>
          <IconButton
            icon="search"
            glass
            label="Search files"
            onPress={() => router.push('/files')}
          />
          <IconButton icon="bell" glass label="Alerts" onPress={() => router.push('/alerts')} />
        </>
      }
    >
      {money === undefined ? (
        <Loading />
      ) : (
        <Hero
          label={money?.label ?? 'Spent today'}
          amount={money?.amount ?? 0}
          delta={money ? money.delta : { text: 'Money is not set up yet', direction: 'flat' }}
          palette={palette}
        />
      )}

      <View style={styles.pills}>
        <View style={styles.pill}>
          <Button
            label="Ask agent"
            icon="message-circle"
            tone="plain"
            onPress={() => router.navigate('/chat')}
          />
        </View>
        <View style={styles.pill}>
          <Button
            label="Approvals"
            icon="shield"
            accessibilityLabel={
              status.pendingCount ? `Approvals, ${status.pendingCount} pending` : 'Approvals'
            }
            onPress={() => router.navigate('/approvals')}
            trailing={
              status.pendingCount ? (
                <View style={styles.count}>
                  <Text style={styles.countText} maxFontSizeMultiplier={1.2}>
                    {status.pendingCount > 99 ? '99+' : status.pendingCount}
                  </Text>
                </View>
              ) : null
            }
          />
        </View>
      </View>

      <ListSection title="Quick Access">
        <QuickAccess items={quick} />
      </ListSection>

      <ErrorText message={error} />
      {!today && !error ? <Loading /> : null}
      {today ? (
        <>
          <ListSection title="Important mail" stagger>
            {today.mail === null ? <EmptyRow>{NOT_CONFIGURED}</EmptyRow> : null}
            {today.mail && important.length === 0 ? (
              <EmptyRow>Nothing important. Enjoy the quiet.</EmptyRow>
            ) : null}
            {important.map((mail) => (
              <MailRow
                key={`${mail.account}:${mail.id}`}
                mail={mail}
                unread
                onPress={() => openMail(mail)}
              />
            ))}
          </ListSection>

          <ListSection
            title="Deadlines"
            stagger
            footer={deadlineCount ? 'Tap one to ask the agent about it.' : undefined}
          >
            {!upcoming && today.deadlines === null ? <EmptyRow>{NOT_CONFIGURED}</EmptyRow> : null}
            {(upcoming ? upcoming.length === 0 : today.deadlines?.length === 0) ? (
              <EmptyRow>No upcoming deadlines.</EmptyRow>
            ) : null}
            {upcoming?.map((d) => (
              <ListRow
                key={`deadline:${d.id}`}
                icon="flag"
                iconTint={palette.warn}
                title={d.title}
                subtitle={dueLabel(d.due)}
                meta={d.calendar_added ? <Badge label="On calendar" tone="ok" /> : undefined}
                accessibilityHint="Asks the agent about this deadline"
                onPress={() =>
                  openNewChat(router, askAboutDeadline({ title: d.title, due: d.due }))
                }
              />
            ))}
            {!upcoming
              ? today.deadlines?.map((d, i) => (
                  <ListRow
                    key={`${d.course ?? ''}:${d.title ?? ''}:${i}`}
                    icon="flag"
                    iconTint={palette.warn}
                    title={String(d.title ?? '')}
                    subtitle={[d.course, shortDateTime(d.due)].filter(Boolean).join(' · ')}
                    accessibilityHint="Asks the agent about this deadline"
                    onPress={() => openNewChat(router, askAboutDeadline(d))}
                  />
                ))
              : null}
          </ListSection>

          <View onLayout={(e) => (offsets.current.events = e.nativeEvent.layout.y)}>
            <ListSection title="Events" stagger>
              {today.events === null ? <EmptyRow>{NOT_CONFIGURED}</EmptyRow> : null}
              {today.events?.length === 0 ? <EmptyRow>No events today.</EmptyRow> : null}
              {today.events?.map((e, i) => (
                <ListRow
                  key={`${e.id ?? ''}:${i}`}
                  icon="calendar"
                  title={String(e.summary ?? '')}
                  subtitle={e.location || null}
                  value={rowTime(e.start) || null}
                  valueMuted
                  accessibilityHint="Asks the agent about this event"
                  onPress={() => openNewChat(router, askAboutEvent(e))}
                />
              ))}
            </ListSection>
          </View>

          <View
            style={{ gap: space.lg }}
            onLayout={(e) => (offsets.current.mail = e.nativeEvent.layout.y)}
          >
            <ListSection
              title="All mail"
              footer={
                inboxError ? (
                  <EmptyRow>{inboxError}</EmptyRow>
                ) : inbox && groups.length === 0 && !inbox.next ? (
                  <EmptyRow>No other mail.</EmptyRow>
                ) : undefined
              }
            >
              {null}
            </ListSection>
            {groups.map((group) => (
              <ListSection key={group.category} title={`${group.title} (${group.count})`}>
                {group.items.map((mail) => (
                  <MailRow
                    key={mailKey(mail)}
                    mail={mail}
                    unread={mail.unread}
                    onPress={() => openMail(mail)}
                  />
                ))}
              </ListSection>
            ))}
            {inbox?.next ? (
              <Button
                label={loadingMore ? 'Loading…' : 'Load more'}
                tone="tinted"
                disabled={loadingMore}
                onPress={() => void loadMore()}
              />
            ) : null}
          </View>
        </>
      ) : null}
    </Screen>
  );
}
