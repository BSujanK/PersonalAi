import { useLocalSearchParams, useRouter } from 'expo-router';
import { useCallback, useMemo, useRef, useState } from 'react';
import { View } from 'react-native';
import type Animated from 'react-native-reanimated';

import { MailCard } from '../src/components/MailCard';
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
import { useAccountLabels } from '../src/lib/accountLabels';
import { askAboutDeadline, askAboutEvent } from '../src/lib/agentPrompts';
import {
  ApiError,
  getDeadlines,
  getToday,
  type Today,
  type UpcomingDeadline,
} from '../src/lib/api';
import { openNewChat } from '../src/lib/chatRoutes';
import { dueLabel, errorMessage, longDate, rowTime, shortDateTime } from '../src/lib/format';
import { usePolling } from '../src/lib/usePolling';
import { space, useTheme } from '../src/theme';

const DEADLINE_DAYS = 7;
const NOT_CONFIGURED = 'Not configured on the laptop yet.';

/**
 * Today: important mail, deadlines and events. Reached from More and the digest chip; "See all
 * mail" opens the full inbox.
 */
export default function TodayScreen() {
  const router = useRouter();
  const { palette } = useTheme();
  const labelFor = useAccountLabels();
  const { focus } = useLocalSearchParams<{ focus?: string }>();
  const scroll = useRef<Animated.ScrollView>(null);
  const offsets = useRef<Record<'mail' | 'events', number>>({ mail: 0, events: 0 });
  const [today, setToday] = useState<Today | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // null until loaded, or when the agent has no /deadlines (then today's own list is shown).
  const [upcoming, setUpcoming] = useState<UpcomingDeadline[] | null>(null);

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
  }, []);

  usePolling(load);

  async function refresh() {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }

  const important = useMemo(() => today?.mail?.important ?? [], [today]);
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
          <ListSection
            title="Important mail"
            stagger
            footer={
              <View style={{ paddingTop: space.sm + space.xs }}>
                <Button
                  label="See all mail"
                  icon="inbox"
                  tone="plain"
                  accessibilityHint="Opens every synced mail, grouped by category"
                  onPress={() => router.push('/inbox')}
                />
              </View>
            }
          >
            {today.mail === null ? <EmptyRow>{NOT_CONFIGURED}</EmptyRow> : null}
            {today.mail && important.length === 0 ? (
              <EmptyRow>Nothing important. Enjoy the quiet.</EmptyRow>
            ) : null}
            {important.map((mail) => (
              <MailCard
                key={`${mail.account}:${mail.id}`}
                mail={mail}
                accountLabel={labelFor(mail.account)}
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
        </>
      ) : null}
    </Screen>
  );
}
