import { useRouter } from 'expo-router';
import { useCallback, useState } from 'react';
import { Switch, Text, View } from 'react-native';

import { Screen } from '../src/components/Screen';
import {
  Button,
  EmptyRow,
  ErrorText,
  ListRow,
  ListSection,
  Loading,
  Notice,
  TextField,
} from '../src/components/ui';
import { alertsPermitted, requestAlertPermission, routeForTarget } from '../src/lib/alerts';
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
import { usePolling } from '../src/lib/usePolling';
import { space, type, useTheme, useThemedStyles, type Palette } from '../src/theme';
import type { IconName } from '../src/components/Icon';

const makeStyles = (p: Palette) => ({
  time: { ...type.footnote, color: p.textMuted },
  undo: { alignSelf: 'flex-start' as const, paddingTop: space.xs },
  padded: { padding: space.md - space.xs },
  field: { flexDirection: 'row' as const, alignItems: 'center' as const, gap: space.sm },
});

const KIND_ICON: Record<AlertKind, IconName> = {
  important_mail: 'mail',
  deadline: 'flag',
  briefing: 'sun',
  calendar_added: 'calendar',
};

/** The deadline an auto-added calendar event came from, the only thing Undo needs. */
const undoableDeadline = (item: AlertItem): number | null =>
  item.kind === 'calendar_added' && item.target.type === 'deadline'
    ? item.target.deadline_id
    : null;

export default function Alerts() {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  const router = useRouter();
  const [items, setItems] = useState<AlertItem[] | null>(null);
  const [feedMissing, setFeedMissing] = useState(false);
  const [feedError, setFeedError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [undoing, setUndoing] = useState<number | null>(null);
  const [alerts, setAlerts] = useState<AlertSettings | null>(null);
  const [alertsMissing, setAlertsMissing] = useState(false);
  const [briefingTime, setBriefingTime] = useState('');
  const [permitted, setPermitted] = useState<boolean | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadFeed = useCallback(async () => {
    try {
      const feed = await getNotifications(0);
      setItems([...feed.items].sort((a, b) => b.id - a.id));
      setFeedMissing(false);
      setFeedError(null);
    } catch (e) {
      // An older agent has no feed; anything else shows on the next poll.
      if (e instanceof ApiError && e.status === 404) {
        setItems([]);
        setFeedMissing(true);
        setFeedError(null);
      } else {
        setFeedError(errorMessage(e));
      }
    }
  }, []);

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

  const load = useCallback(async () => {
    await Promise.all([loadFeed(), loadAlerts()]);
  }, [loadFeed, loadAlerts]);

  usePolling(load);

  async function refresh() {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }

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
        await loadFeed();
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

  const switchColors = {
    trackColor: { true: palette.accentStrong, false: palette.border },
    thumbColor: palette.accentOn,
  };

  return (
    <Screen
      title="Alerts"
      subtitle="What the agent found, and what to tell you about"
      back
      refreshing={refreshing}
      onRefresh={() => void refresh()}
    >
      <ErrorText message={error} />
      <ErrorText message={feedError} />
      {status ? <Notice tone="ok">{status}</Notice> : null}

      <ListSection title="Recent" stagger>
        {items === null && !feedError ? <Loading /> : null}
        {items?.length === 0 ? (
          <EmptyRow>
            {feedMissing
              ? 'This agent does not support alerts yet. Update it on the laptop.'
              : 'No alerts yet.'}
          </EmptyRow>
        ) : null}
        {items?.map((item) => {
          const deadlineId = undoableDeadline(item);
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
              onPress={() => router.push(routeForTarget(item.target))}
            >
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
              {...switchColors}
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
              {...switchColors}
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
              {...switchColors}
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
