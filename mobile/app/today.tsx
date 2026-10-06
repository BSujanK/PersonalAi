import { useLocalSearchParams, useRouter } from 'expo-router';
import { useCallback, useMemo, useRef, useState } from 'react';
import { Text, View } from 'react-native';
import type Animated from 'react-native-reanimated';

import { Screen } from '../src/components/Screen';
import {
  Badge,
  Button,
  EmptyRow,
  ErrorText,
  ListRow,
  ListSection,
  Loading,
} from '../src/components/ui';
import { askAboutDeadline, askAboutEvent } from '../src/lib/agentPrompts';
import {
  ApiError,
  getDeadlines,
  getInbox,
  getToday,
  type DigestItem,
  type InboxCategory,
  type InboxItem,
  type Today,
  type UpcomingDeadline,
} from '../src/lib/api';
import { openNewChat } from '../src/lib/chatRoutes';
import {
  dueLabel,
  errorMessage,
  initials,
  longDate,
  rowTime,
  shortDateTime,
} from '../src/lib/format';
import { appendPage, groupInbox, mailKey } from '../src/lib/inbox';
import { usePolling } from '../src/lib/usePolling';
import { fontFamily, space, type, useTheme, useThemedStyles, type Palette } from '../src/theme';

const INBOX_PAGE = 50;
const DEADLINE_DAYS = 7;
const NOT_CONFIGURED = 'Not configured on the laptop yet.';
const AVATAR = 40;

const makeStyles = (p: Palette) => ({
  avatar: {
    width: AVATAR,
    height: AVATAR,
    borderRadius: AVATAR / 2,
    backgroundColor: p.accentSoft,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
  },
  avatarText: { ...type.subheadline, fontFamily: fontFamily.bodySemiBold, color: p.accentText },
});

interface Inbox {
  items: InboxItem[];
  counts: Record<InboxCategory, number>;
  next: string | null;
  /** Pages loaded by "Load more", beyond the first. */
  extraPages: number;
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

/** Today: important mail, deadlines, events and all mail. Reached from More and the chat chips. */
export default function TodayScreen() {
  const router = useRouter();
  const { palette } = useTheme();
  const { focus } = useLocalSearchParams<{ focus?: string }>();
  const scroll = useRef<Animated.ScrollView>(null);
  const offsets = useRef<Record<'mail' | 'events', number>>({ mail: 0, events: 0 });
  const [today, setToday] = useState<Today | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // null until loaded, or when the agent has no /deadlines (then today's own list is shown).
  const [upcoming, setUpcoming] = useState<UpcomingDeadline[] | null>(null);
  const [inbox, setInbox] = useState<Inbox | null>(null);
  const [inboxError, setInboxError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  const load = useCallback(async () => {
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
  const deadlineCount = upcoming?.length ?? today?.deadlines?.length ?? 0;
  const openMail = (mail: { account: string; id: string }) =>
    router.push({
      pathname: '/mail/[account]/[id]',
      params: { account: mail.account, id: mail.id },
    });
  // Opened from "Mail" or "Calendar" in Chat's Quick Access: scroll to that list once it is laid out.
  const focused = useRef(false);
  const focusOn = (key: 'mail' | 'events', y: number) => {
    offsets.current[key] = y;
    if (focused.current || focus !== key) return;
    focused.current = true;
    requestAnimationFrame(() =>
      scroll.current?.scrollTo({ y: Math.max(0, y - space.md), animated: true }),
    );
  };

  return (
    <Screen
      title="Today"
      subtitle={longDate()}
      back
      scrollRef={scroll}
      refreshing={refreshing}
      onRefresh={() => void refresh()}
    >
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

          <View onLayout={(e) => focusOn('events', e.nativeEvent.layout.y)}>
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

          <View style={{ gap: space.lg }} onLayout={(e) => focusOn('mail', e.nativeEvent.layout.y)}>
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
