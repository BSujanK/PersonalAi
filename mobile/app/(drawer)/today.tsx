import { useRouter } from 'expo-router';
import { useCallback, useMemo, useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { Screen } from '../../src/components/Screen';
import {
  Badge,
  Button,
  EmptyRow,
  ErrorText,
  ListRow,
  ListSection,
  Loading,
} from '../../src/components/ui';
import { askAboutDeadline, askAboutEvent } from '../../src/lib/agentPrompts';
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
} from '../../src/lib/api';
import { openNewChat } from '../../src/lib/chatRoutes';
import {
  dueLabel,
  errorMessage,
  initials,
  longDate,
  rowTime,
  shortDateTime,
} from '../../src/lib/format';
import { appendPage, groupInbox, mailKey } from '../../src/lib/inbox';
import { usePolling } from '../../src/lib/usePolling';
import {
  fontFamily,
  MIN_TARGET,
  ROW_INSET,
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
/** Mail row hairlines start under the text, after the avatar. */
const MAIL_INSET = ROW_INSET + AVATAR + space.md - space.xs;

const makeStyles = (p: Palette) => ({
  mailRow: {
    minHeight: MIN_TARGET + 4,
    flexDirection: 'row' as const,
    gap: space.md - space.xs,
    paddingHorizontal: ROW_INSET,
    paddingVertical: space.sm + space.xs,
    backgroundColor: p.surface,
  },
  mailRowPressed: { backgroundColor: p.muted },
  avatar: {
    width: AVATAR,
    height: AVATAR,
    borderRadius: AVATAR / 2,
    backgroundColor: p.accentSoft,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
  },
  avatarText: { ...type.subhead, fontFamily: fontFamily.bodySemiBold, color: p.accentText },
  mailMain: { flex: 1, gap: 2 },
  mailTop: { flexDirection: 'row' as const, alignItems: 'baseline' as const, gap: space.sm },
  sender: { ...type.headline, color: p.text, flex: 1 },
  time: { ...type.footnote, color: p.textMuted },
  subject: { ...type.subhead, fontFamily: fontFamily.bodyMedium, color: p.text },
  snippet: { ...type.subhead, color: p.textMuted },
  reason: { marginTop: space.xs },
});

function MailRow({ mail, onPress }: { mail: DigestItem | InboxItem; onPress: () => void }) {
  const styles = useThemedStyles(makeStyles);
  const sender = mail.from_name || mail.from_addr;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`Mail from ${sender}: ${mail.subject}. ${rowTime(mail.received)}`}
      accessibilityHint="Opens the full message"
      onPress={onPress}
      pressRetentionOffset={16}
      style={({ pressed }) => [styles.mailRow, pressed && styles.mailRowPressed]}
    >
      <View style={styles.avatar}>
        <Text style={styles.avatarText} maxFontSizeMultiplier={1.3}>
          {initials(sender)}
        </Text>
      </View>
      <View style={styles.mailMain}>
        <View style={styles.mailTop}>
          <Text numberOfLines={1} style={styles.sender}>
            {sender}
          </Text>
          <Text style={styles.time}>{rowTime(mail.received)}</Text>
        </View>
        <Text numberOfLines={1} style={styles.subject}>
          {mail.subject || '(no subject)'}
        </Text>
        {mail.snippet ? (
          <Text numberOfLines={2} style={styles.snippet}>
            {mail.snippet}
          </Text>
        ) : null}
        {mail.reason ? (
          <View style={styles.reason}>
            <Badge label={mail.reason} tone="accent" />
          </View>
        ) : null}
      </View>
    </Pressable>
  );
}

interface Inbox {
  items: InboxItem[];
  counts: Record<InboxCategory, number>;
  next: string | null;
  /** Pages loaded by "Load more", beyond the first. */
  extraPages: number;
}

export default function TodayScreen() {
  const router = useRouter();
  const { palette } = useTheme();
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
  const openMail = (mail: { account: string; id: string }) =>
    router.push({
      pathname: '/mail/[account]/[id]',
      params: { account: mail.account, id: mail.id },
    });

  return (
    <Screen
      title="Today"
      subtitle={longDate()}
      menu
      refreshing={refreshing}
      onRefresh={() => void refresh()}
    >
      <ErrorText message={error} />
      {!today && !error ? <Loading /> : null}
      {today ? (
        <>
          <ListSection title="Important mail" inset={MAIL_INSET}>
            {today.mail === null ? <EmptyRow>{NOT_CONFIGURED}</EmptyRow> : null}
            {today.mail && important.length === 0 ? (
              <EmptyRow>Nothing important. Enjoy the quiet.</EmptyRow>
            ) : null}
            {important.map((mail) => (
              <MailRow
                key={`${mail.account}:${mail.id}`}
                mail={mail}
                onPress={() => openMail(mail)}
              />
            ))}
          </ListSection>

          <ListSection
            title="All mail"
            inset={MAIL_INSET}
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
            <ListSection
              key={group.category}
              title={`${group.title} (${group.count})`}
              inset={MAIL_INSET}
            >
              {group.items.map((mail) => (
                <MailRow key={mailKey(mail)} mail={mail} onPress={() => openMail(mail)} />
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

          <ListSection
            title="Deadlines"
            inset="icon"
            footer={
              upcoming?.length || today.deadlines?.length
                ? 'Tap one to ask the agent about it.'
                : undefined
            }
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
                meta={d.calendar_added ? <Badge label="On calendar" tone="accent" /> : undefined}
                chevron
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
                    chevron
                    accessibilityHint="Asks the agent about this deadline"
                    onPress={() => openNewChat(router, askAboutDeadline(d))}
                  />
                ))
              : null}
          </ListSection>

          <ListSection title="Events" inset="icon">
            {today.events === null ? <EmptyRow>{NOT_CONFIGURED}</EmptyRow> : null}
            {today.events?.length === 0 ? <EmptyRow>No events.</EmptyRow> : null}
            {today.events?.map((e, i) => (
              <ListRow
                key={`${e.id ?? ''}:${i}`}
                icon="calendar"
                title={String(e.summary ?? '')}
                subtitle={[shortDateTime(e.start), e.location].filter(Boolean).join(' · ')}
                chevron
                accessibilityHint="Asks the agent about this event"
                onPress={() => openNewChat(router, askAboutEvent(e))}
              />
            ))}
          </ListSection>
        </>
      ) : null}
    </Screen>
  );
}
