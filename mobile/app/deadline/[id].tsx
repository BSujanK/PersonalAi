import { useLocalSearchParams, useRouter } from 'expo-router';
import { useCallback, useState } from 'react';
import { Linking, Text, View } from 'react-native';

import { Screen } from '../../src/components/Screen';
import { SkeletonBlock, SkeletonGroup, SkeletonRows } from '../../src/components/Skeleton';
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
} from '../../src/components/ui';
import { useAccountLabels } from '../../src/lib/accountLabels';
import { askAboutDeadline } from '../../src/lib/agentPrompts';
import { ApiError, getDeadline, undoAutoEvent, type DeadlineDetail } from '../../src/lib/api';
import { openNewChat } from '../../src/lib/chatRoutes';
import { dueLabel, errorMessage, fullDateTime } from '../../src/lib/format';
import { isGoogleCalendarLink } from '../../src/lib/links';
import { useLoader, usePullToRefresh } from '../../src/lib/usePolling';
import { space, type, useTheme, useThemedStyles, type Palette } from '../../src/theme';

const makeStyles = (p: Palette) => ({
  head: { gap: space.sm },
  due: { ...type.headline, color: p.text },
  dueFull: { ...type.subheadline, color: p.textMuted },
  chips: { flexDirection: 'row' as const, flexWrap: 'wrap' as const, gap: space.sm },
  undo: { alignSelf: 'flex-start' as const, paddingTop: space.xs },
});

/** One tracked deadline: when it is due, where it came from and whether it is on the calendar. */
export default function DeadlineScreen() {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  const router = useRouter();
  const labelFor = useAccountLabels();
  const { id } = useLocalSearchParams<{ id: string }>();
  const fetchDeadline = useCallback(async (): Promise<{ deadline: DeadlineDetail | null }> => {
    try {
      return { deadline: await getDeadline(Number(id)) };
    } catch (e) {
      // Gone: dismissed, or cleared from the agent.
      if (e instanceof ApiError && e.status === 404) return { deadline: null };
      throw e;
    }
  }, [id]);
  const { data, error, loading, failing, retrying, reload } = useLoader(fetchDeadline);
  const pull = usePullToRefresh(reload);
  const [undoing, setUndoing] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const deadline = data?.deadline ?? null;

  async function undo(deadlineId: number) {
    setActionError(null);
    setStatus(null);
    setUndoing(true);
    try {
      await undoAutoEvent(deadlineId);
      setStatus('Removed from your calendar');
      await reload();
    } catch (e) {
      setActionError(errorMessage(e));
    } finally {
      setUndoing(false);
    }
  }

  const accountLabel = deadline
    ? (deadline.source_label ?? labelFor(deadline.source_account))
    : null;
  const calendar = deadline?.calendar ?? null;

  return (
    <Screen title={deadline?.title ?? 'Deadline'} back {...pull}>
      {failing && data ? <StaleNote /> : null}
      {failing && !data ? <LoadFailed what="this deadline" reason={errorMessage(error)} retrying={retrying} /> : null}
      {loading ? (
        <>
          <SkeletonGroup>
            <View style={styles.head}>
              <SkeletonBlock width="50%" height={18} />
              <SkeletonBlock width="70%" height={14} />
            </View>
          </SkeletonGroup>
          <SkeletonRows count={2} />
        </>
      ) : null}
      {data && !deadline ? <EmptyRow>This deadline is no longer tracked.</EmptyRow> : null}
      {deadline ? (
        <>
          <View style={styles.head}>
            <Text style={styles.due}>{dueLabel(deadline.due)}</Text>
            <Text style={styles.dueFull}>{fullDateTime(deadline.due)}</Text>
            {accountLabel ? (
              <View style={styles.chips}>
                <Badge
                  label={accountLabel}
                  tone="neutral"
                  icon="inbox"
                  spoken={`From ${accountLabel}`}
                />
              </View>
            ) : null}
          </View>

          {deadline.source === 'mail' || deadline.source === 'classroom' ? (
            <ListSection title="Source">
              {deadline.source === 'mail' ? (
                <ListRow
                  icon="mail"
                  title="Open the mail it came from"
                  chevron
                  accessibilityHint="Opens the message this deadline was found in"
                  onPress={() =>
                    router.push({
                      pathname: '/mail/[account]/[id]',
                      params: {
                        account: deadline.source_account,
                        id: deadline.message_id ?? deadline.source_id,
                      },
                    })
                  }
                />
              ) : (
                <ListRow icon="book-open" title="From Google Classroom" />
              )}
            </ListSection>
          ) : null}

          <ListSection title="Calendar">
            {status ? <Notice tone="ok">{status}</Notice> : null}
            <ErrorText message={actionError} />
            {calendar ? (
              <ListRow
                icon="calendar"
                iconTint={palette.ok}
                title="On your calendar"
                subtitle={calendar.account}
                meta={<Badge label="Added" tone="ok" icon="check" />}
              >
                <View style={styles.undo}>
                  <Button
                    label="Undo"
                    tone="dangerTinted"
                    compact
                    disabled={undoing}
                    accessibilityHint="Removes the event the agent added to your calendar"
                    onPress={() => void undo(deadline.id)}
                  />
                </View>
              </ListRow>
            ) : (
              <ListRow icon="calendar" iconTint={palette.textMuted} title="Not on your calendar" />
            )}
            {calendar && isGoogleCalendarLink(calendar.link) ? (
              <ListRow
                icon="external-link"
                title="Open in Google Calendar"
                chevron
                accessibilityHint="Opens the event in your browser"
                onPress={() =>
                  Linking.openURL(calendar.link).catch(() =>
                    setActionError('Could not open Google Calendar.'),
                  )
                }
              />
            ) : null}
          </ListSection>

          <Button
            label="Ask the agent about it"
            icon="message-circle"
            tone="tinted"
            accessibilityHint="Starts a chat about this deadline"
            onPress={() =>
              openNewChat(router, askAboutDeadline({ title: deadline.title, due: deadline.due }))
            }
          />
        </>
      ) : null}
    </Screen>
  );
}
