import { useState } from 'react';
import { ActivityIndicator, Pressable, Text, View } from 'react-native';

import {
  summariseTools,
  toolSummaryLine,
  type ToolActivity as Activity,
} from '../../lib/toolLabels';
import { fontFamily, MIN_TARGET, size, useTheme, useThemedStyles, type Palette } from '../../theme';
import { Icon } from '../Icon';

const makeStyles = (p: Palette) => ({
  root: { gap: 6, alignItems: 'flex-start' as const },
  summary: {
    minHeight: MIN_TARGET,
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    gap: 8,
    paddingHorizontal: 12,
    borderRadius: MIN_TARGET / 2,
    borderWidth: 1,
    borderColor: p.border,
    backgroundColor: p.surface,
    maxWidth: '100%' as const,
  },
  summaryText: {
    flexShrink: 1,
    fontFamily: fontFamily.body,
    fontSize: size.small + 1,
    color: p.textMuted,
  },
  list: { gap: 6, paddingLeft: 4 },
  chip: {
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    gap: 8,
    paddingVertical: 4,
    paddingHorizontal: 12,
    borderRadius: 14,
    backgroundColor: p.muted,
    alignSelf: 'flex-start' as const,
  },
  chipText: { fontFamily: fontFamily.body, fontSize: size.small, color: p.text },
});

function StatusIcon({ status }: { status: Activity['status'] }) {
  const { palette } = useTheme();
  if (status === 'started') return <ActivityIndicator size="small" color={palette.accent} />;
  if (status === 'failed') return <Icon name="alert-circle" size={16} color={palette.danger} />;
  return <Icon name="check" size={16} color={palette.ok} />;
}

/** What the agent did this turn, collapsed to one line; tap to see each step. */
export function ToolActivity({ activity }: { activity: Activity[] }) {
  const styles = useThemedStyles(makeStyles);
  const [open, setOpen] = useState(false);
  if (activity.length === 0) return null;
  const chips = summariseTools(activity);
  const anyRunning = activity.some((a) => a.status === 'started');
  const anyFailed = activity.some((a) => a.status === 'failed');
  const status = anyRunning ? 'started' : anyFailed ? 'failed' : 'finished';
  const summary = toolSummaryLine(activity);
  return (
    <View style={styles.root}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`${summary}. ${open ? 'Hide' : 'Show'} steps`}
        accessibilityState={{ expanded: open }}
        onPress={() => setOpen((v) => !v)}
        style={styles.summary}
      >
        <StatusIcon status={status} />
        <Text style={styles.summaryText} numberOfLines={1}>
          {summary}
        </Text>
        <Icon name={open ? 'chevron-up' : 'chevron-down'} size={16} />
      </Pressable>
      {open ? (
        <View style={styles.list}>
          {chips.map((chip) => (
            <View key={chip.key} style={styles.chip}>
              <StatusIcon status={chip.status} />
              <Text style={styles.chipText}>
                {chip.label}
                {chip.status === 'failed' ? ' (failed)' : ''}
                {chip.count > 1 ? ` ×${chip.count}` : ''}
              </Text>
            </View>
          ))}
        </View>
      ) : null}
    </View>
  );
}
