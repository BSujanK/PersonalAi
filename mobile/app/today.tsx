import { useLocalSearchParams, useRouter } from 'expo-router';
import { useCallback, useEffect, useRef, type ReactNode } from 'react';
import { View } from 'react-native';
import type Animated from 'react-native-reanimated';

import { MailCard } from '../src/components/MailCard';
import { Screen } from '../src/components/Screen';
import { SkeletonRows } from '../src/components/Skeleton';
import {
  Badge,
  Button,
  EmptyRow,
  ListRow,
  ListSection,
  LoadFailed,
  StaleNote,
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
import { useLoader, usePullToRefresh, type Loader } from '../src/lib/usePolling';
import { space, useTheme } from '../src/theme';

const DEADLINE_DAYS = 7;
const NOT_CONFIGURED = 'Not configured on the laptop yet.';

/** The tools behind each section; /today lists the ones that failed just now in `unavailable`. */
const EVENTS_TOOL = 'calendar_events';
const DEADLINES_TOOL = 'classroom_coursework';

const fetchMail = () => getToday(['mail']);
const fetchEvents = () => getToday(['events']);

/** Deadlines from /deadlines, or from /today for an agent that has no such route yet. */
type DeadlineList =
  | { from: 'deadlines'; items: UpcomingDeadline[] }
  | { from: 'today'; today: Today };

async function fetchDeadlines(): Promise<DeadlineList> {
  try {
    const { items } = await getDeadlines(DEADLINE_DAYS);
    return { from: 'deadlines', items: items.filter((d) => d.status === 'active') };
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      return { from: 'today', today: await getToday(['deadlines']) };
    }
    throw e;
  }
}

/**
 * What a section shows before its rows: a skeleton while the first answer is on its way, a quiet
 * failure card when there is nothing to show, and a note above older data that failed to refresh.
 */
function sectionStatus<T>(loader: Loader<T>, what: string, skeleton: ReactNode): ReactNode {
  if (loader.loading) return skeleton;
  if (!loader.failing) return null;
  return loader.data ? (
    <StaleNote />
  ) : (
    <LoadFailed what={what} reason={errorMessage(loader.error)} retrying={loader.retrying} />
  );
}

/**
 * Today: important mail, deadlines and events. Reached from More and the digest chip; "See all
 * mail" opens the full inbox. Each section loads on its own and shows up as soon as it arrives.
 */
export default function TodayScreen() {
  const router = useRouter();
  const { palette } = useTheme();
  const labelFor = useAccountLabels();
  const { focus } = useLocalSearchParams<{ focus?: string }>();
  const scroll = useRef<Animated.ScrollView>(null);
  const eventsY = useRef(0);
  const mail = useLoader(fetchMail);
  const events = useLoader(fetchEvents);
  const deadlines = useLoader(fetchDeadlines);
  const { reload: reloadMail } = mail;
  const { reload: reloadEvents } = events;
  const { reload: reloadDeadlines } = deadlines;
  const pull = usePullToRefresh(
    useCallback(async () => {
      await Promise.all([reloadMail(), reloadEvents(), reloadDeadlines()]);
    }, [reloadMail, reloadEvents, reloadDeadlines]),
  );

  const digest = mail.data?.mail;
  const important = digest?.important ?? [];
  const eventList = events.data?.events;
  const eventsDown = events.data?.unavailable?.includes(EVENTS_TOOL) ?? false;
  const upcoming = deadlines.data?.from === 'deadlines' ? deadlines.data.items : null;
  const fallback = deadlines.data?.from === 'today' ? deadlines.data.today : null;
  const fallbackList = fallback?.deadlines;
  const deadlinesDown = fallback?.unavailable?.includes(DEADLINES_TOOL) ?? false;
  const deadlineCount = upcoming?.length ?? fallbackList?.length ?? 0;

  const openMail = (item: { account: string; id: string }) =>
    router.push({
      pathname: '/mail/[account]/[id]',
      params: { account: item.account, id: item.id },
    });
  // Opened from "Calendar" in Chat's Quick Access: scroll to the events once every section above
  // has settled, because their rows move it down.
  const settled = !mail.loading && !events.loading && !deadlines.loading;
  const focused = useRef(false);
  useEffect(() => {
    if (!settled || focused.current || focus !== 'events') return;
    focused.current = true;
    requestAnimationFrame(() =>
      scroll.current?.scrollTo({ y: Math.max(0, eventsY.current - space.md), animated: true }),
    );
  }, [settled, focus]);

  return (
    <Screen title="Today" subtitle={longDate()} back scrollRef={scroll} {...pull}>
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
        {sectionStatus(mail, 'important mail', <SkeletonRows count={2} avatar />)}
        {mail.data && !digest ? <EmptyRow>{NOT_CONFIGURED}</EmptyRow> : null}
        {digest && important.length === 0 ? (
          <EmptyRow>Nothing important. Enjoy the quiet.</EmptyRow>
        ) : null}
        {important.map((item) => (
          <MailCard
            key={`${item.account}:${item.id}`}
            mail={item}
            accountLabel={labelFor(item.account)}
            onPress={() => openMail(item)}
          />
        ))}
      </ListSection>

      <ListSection
        title="Deadlines"
        stagger
        footer={
          deadlineCount
            ? upcoming
              ? 'Tap one to see where it came from.'
              : 'Tap one to ask the agent about it.'
            : undefined
        }
      >
        {sectionStatus(deadlines, 'deadlines', <SkeletonRows count={2} />)}
        {fallback && !fallbackList && !deadlinesDown ? <EmptyRow>{NOT_CONFIGURED}</EmptyRow> : null}
        {fallback && !fallbackList && deadlinesDown ? <LoadFailed what="deadlines" /> : null}
        {upcoming?.length === 0 || fallbackList?.length === 0 ? (
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
            chevron
            accessibilityHint="Opens the deadline"
            onPress={() =>
              router.push({ pathname: '/deadline/[id]', params: { id: String(d.id) } })
            }
          />
        ))}
        {fallbackList?.map((d, i) => (
          <ListRow
            key={`${d.course ?? ''}:${d.title ?? ''}:${i}`}
            icon="flag"
            iconTint={palette.warn}
            title={String(d.title ?? '')}
            subtitle={[d.course, shortDateTime(d.due)].filter(Boolean).join(' · ')}
            accessibilityHint="Asks the agent about this deadline"
            onPress={() => openNewChat(router, askAboutDeadline(d))}
          />
        ))}
      </ListSection>

      <View
        onLayout={(e) => {
          eventsY.current = e.nativeEvent.layout.y;
        }}
      >
        <ListSection title="Events" stagger>
          {sectionStatus(events, 'events', <SkeletonRows count={2} />)}
          {events.data && !eventList && !eventsDown ? <EmptyRow>{NOT_CONFIGURED}</EmptyRow> : null}
          {events.data && !eventList && eventsDown ? <LoadFailed what="events" /> : null}
          {eventList?.length === 0 ? <EmptyRow>No events today.</EmptyRow> : null}
          {eventList?.map((e, i) => (
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
    </Screen>
  );
}
