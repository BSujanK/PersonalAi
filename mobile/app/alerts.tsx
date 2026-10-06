import { useRouter } from 'expo-router';
import { useCallback, useState } from 'react';
import { Switch, Text, View } from 'react-native';

import { Screen } from '../src/components/Screen';
import { SkeletonRows } from '../src/components/Skeleton';
import {
  Badge,
  Button,
  EmptyRow,
  ErrorText,
  ListRow,
  ListSection,
  LoadFailed,
  Notice,
  StaleNote,
  TextField,
  switchColors,
} from '../src/components/ui';
import {
  alertAccount,
  alertsPermitted,
  requestAlertPermission,
  routeForTarget,
  type AlertRoute,
} from '../src/lib/alerts';
import { useAccountLabels } from '../src/lib/accountLabels';
import {
  ApiError,
  getAlertSettings,
  getNotifications,
  putAlertSettings,
  undoAutoEvent,
  type AlertItem,
  type AlertKind,
  type AlertSettings,
} from '../src/lib/api';
import { isValidBriefingTime } from '../src/lib/briefingTime';
import { errorMessage, rowTime } from '../src/lib/format';
import { useLoader, usePolling, usePullToRefresh } from '../src/lib/usePolling';
import { space, type, useTheme, useThemedStyles, type Palette } from '../src/theme';
import type { IconName } from '../src/components/Icon';

const makeStyles = (p: Palette) => ({
  time: { ...type.footnote, color: p.textMuted },
  undo: { alignSelf: 'flex-start' as const, paddingTop: space.xs },
  source: { paddingTop: space.xs },
  padded: { padding: space.md - space.xs },
  field: { flexDirection: 'row' as const, alignItems: 'center' as const, gap: space.sm },
});

const KIND_ICON: Record<AlertKind, IconName> = {
  important_mail: 'mail',
  deadline: 'flag',
  briefing: 'sun',
  calendar_added: 'calendar',
};

const DESTINATION: Record<AlertRoute['pathname'], string> = {
  '/mail/[account]/[id]': 'Opens the mail',
  '/inbox': 'Opens all mail',
  '/deadline/[id]': 'Opens the deadline',
  '/today': 'Opens Today',
  '/approvals': 'Opens Approvals',
};

/** The feed, newest first. An older agent has no feed: that reads as an empty one, flagged. */
async function fetchFeed(): Promise<{ items: AlertItem[]; missing: boolean }> {
  try {
    const feed = await getNotifications(0);
    return { items: [...feed.items].sort((a, b) => b.id - a.id), missing: false };
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return { items: [], missing: true };
    throw e;
  }
}

/** The deadline an auto-added calendar event came from, the only thing Undo needs. */
const undoableDeadline = (item: AlertItem): number | null =>
  item.kind === 'calendar_added' && item.target.type === 'deadline'
    ? item.target.deadline_id
    : null;

export default function Alerts() {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  const router = useRouter();
  const labelFor = useAccountLabels();
  const feed = useLoader(fetchFeed);
  const { reload: reloadFeed } = feed;
  const items = feed.data?.items ?? null;
  const feedMissing = feed.data?.missing ?? false;
  const [undoing, setUndoing] = useState<number | null>(null);
  const [alerts, setAlerts] = useState<AlertSettings | null>(null);
  const [alertsMissing, setAlertsMissing] = useState(false);
  const [briefingTime, setBriefingTime] = useState('');
  const [permitted, setPermitted] = useState<boolean | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadAlerts = useCallback(async () => {
    setPermitted(await alertsPermitted().catch(() => null));
    try {
      const loaded = await getAlertSettings();
      setAlerts(loaded);
      setBriefingTime((current) => current || loaded.briefing_time);
      setAlertsMissing(false);
    } catch (e) {
      // An older agent has no alert settings; anything else shows on the next poll.
      setAlertsMissing(e instanceof ApiError && e.status === 404);
    }
  }, []);

  usePolling(loadAlerts);
  const pull = usePullToRefresh(
    useCallback(async () => {
      await Promise.all([reloadFeed(), loadAlerts()]);
    }, [reloadFeed, loadAlerts]),
  );

  async function run(task: () => Promise<void>) {
    setError(null);
    setStatus(null);
    try {
      await task();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  const undo = (deadlineId: number) =>
    run(async () => {
      setUndoing(deadlineId);
      try {
        await undoAutoEvent(deadlineId);
        setStatus('Removed from your calendar');
        await reloadFeed();
      } finally {
        setUndoing(null);
      }
    });

  const saveAlerts = (next: AlertSettings, turnedOn: boolean) =>
    run(async () => {
      if (turnedOn) setPermitted(await requestAlertPermission());
      const saved = await putAlertSettings(next);
      setAlerts(saved);
      setBriefingTime(saved.briefing_time);
    });

  const toggleAlert = (key: 'important_mail' | 'deadlines' | 'briefing', value: boolean) => {
    if (alerts) void saveAlerts({ ...alerts, [key]: value }, value);
  };

  const timeValid = isValidBriefingTime(briefingTime);
  const timeChanged = alerts !== null && briefingTime !== alerts.briefing_time;

  const saveBriefingTime = () => {
    if (alerts && timeValid) void saveAlerts({ ...alerts, briefing_time: briefingTime }, false);
  };

  const switches = switchColors(palette);

  return (
    <Screen
      title="Alerts"
      subtitle="What the agent found, and what to tell you about"
      back
      {...pull}
    >
      <ErrorText message={error} />
      {status ? <Notice tone="ok">{status}</Notice> : null}

      <ListSection title="Recent" stagger>
        {feed.failing && items ? <StaleNote /> : null}
        {feed.failing && !items ? (
          <LoadFailed what="alerts" reason={errorMessage(feed.error)} />
        ) : null}
        {feed.loading ? <SkeletonRows count={3} /> : null}
        {items?.length === 0 ? (
          <EmptyRow>
            {feedMissing
              ? 'This agent does not support alerts yet. Update it on the laptop.'
              : 'No alerts yet.'}
          </EmptyRow>
        ) : null}
        {items?.map((item) => {
          const deadlineId = undoableDeadline(item);
          const account = alertAccount(item);
          const accountLabel = item.source_label ?? (account ? labelFor(account) : null);
          const route = routeForTarget(item.target, item.kind);
          return (
            <ListRow
              key={item.id}
              icon={KIND_ICON[item.kind]}
              iconTint={
                item.kind === 'deadline'
                  ? palette.warn
                  : item.kind === 'calendar_added'
                    ? palette.ok
                    : undefined
              }
              title={item.title}
              subtitle={item.body}
              meta={<Text style={styles.time}>{rowTime(item.created_at)}</Text>}
              chevron
              accessibilityHint={DESTINATION[route.pathname]}
              onPress={() => router.push(route)}
            >
              {accountLabel ? (
                <View style={styles.source}>
                  <Badge
                    label={accountLabel}
                    tone="neutral"
                    icon="inbox"
                    spoken={`From ${accountLabel}`}
                  />
                </View>
              ) : null}
              {deadlineId !== null ? (
                <View style={styles.undo}>
                  <Button
                    label="Undo"
                    tone="dangerTinted"
                    compact
                    disabled={undoing === deadlineId}
                    accessibilityHint="Removes the event the agent added to your calendar"
                    onPress={() => void undo(deadlineId)}
                  />
                </View>
              ) : null}
            </ListRow>
          );
        })}
      </ListSection>

      <ListSection
        title="Alert settings"
        footer={
          alertsMissing
            ? 'This agent does not support alerts yet. Update it on the laptop.'
            : 'Alerts are made on this phone from what the agent finds, over Tailscale. Their text stays off any push service.'
        }
      >
        {permitted === false ? (
          <Notice tone="warn" title="Notifications are off">
            Alerts need permission to show notifications. Allow it when asked, or turn it on in
            Android settings under Apps, PersonalAi, Notifications.
          </Notice>
        ) : null}
        <ListRow
          icon="mail"
          title="Important mail"
          accessory={
            <Switch
              accessibilityLabel="Important mail alerts"
              value={alerts?.important_mail ?? false}
              onValueChange={(v) => toggleAlert('important_mail', v)}
              disabled={!alerts}
              {...switches}
            />
          }
        />
        <ListRow
          icon="flag"
          title="Deadlines"
          accessory={
            <Switch
              accessibilityLabel="Deadline alerts"
              value={alerts?.deadlines ?? false}
              onValueChange={(v) => toggleAlert('deadlines', v)}
              disabled={!alerts}
              {...switches}
            />
          }
        />
        <ListRow
          icon="sun"
          title="Morning briefing"
          accessory={
            <Switch
              accessibilityLabel="Morning briefing"
              value={alerts?.briefing ?? false}
              onValueChange={(v) => toggleAlert('briefing', v)}
              disabled={!alerts}
              {...switches}
            />
          }
        />
        <View style={[styles.padded, styles.field]}>
          <View style={{ flex: 1 }}>
            <TextField
              accessibilityLabel="Briefing time, 24-hour HH:MM"
              value={briefingTime}
              onChangeText={setBriefingTime}
              placeholder="Briefing time, e.g. 07:30"
              keyboardType="numbers-and-punctuation"
              maxLength={5}
              autoCorrect={false}
              editable={!!alerts}
              onSubmitEditing={saveBriefingTime}
            />
          </View>
          <Button
            label="Save"
            tone="tinted"
            compact
            accessibilityLabel="Save briefing time"
            onPress={saveBriefingTime}
            disabled={!alerts || !timeChanged || !timeValid}
          />
        </View>
        {alerts && briefingTime && !timeValid ? (
          <Notice tone="warn">Use 24-hour time as HH:MM, like 07:30.</Notice>
        ) : null}
      </ListSection>
    </Screen>
  );
}
