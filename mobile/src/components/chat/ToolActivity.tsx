import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import {
  summariseTools,
  toolSummaryLine,
  type ToolActivity as Activity,
} from '../../lib/toolLabels';
import {
  MIN_TARGET,
  radius,
  space,
  type,
  useTheme,
  useThemedStyles,
  type Palette,
} from '../../theme';
import { Spark } from '../brand/Spark';
import { Icon } from '../Icon';

const makeStyles = (p: Palette) => ({
  root: { gap: space.sm, alignItems: 'flex-start' as const },
  summary: {
    minHeight: MIN_TARGET,
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    gap: space.sm,
    paddingHorizontal: space.md - space.xs,
    borderRadius: radius.pill,
    backgroundColor: p.glass,
    borderWidth: 1,
    borderColor: p.glassBorder,
    maxWidth: '100%' as const,
  },
  summaryText: { ...type.subheadline, flexShrink: 1, color: p.textMuted },
  list: { gap: space.xs + 2, paddingLeft: space.xs },
  chip: {
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    gap: space.sm,
    paddingVertical: space.xs,
    paddingHorizontal: space.md - space.xs,
    borderRadius: radius.pill,
    backgroundColor: p.accentSoft,
    alignSelf: 'flex-start' as const,
  },
  chipText: { ...type.footnote, color: p.accentText },
});

function StatusIcon({ status }: { status: Activity['status'] }) {
  const { palette } = useTheme();
  // The reply avatar carries the thinking motion; a running step is a still, dimmed mark.
  if (status === 'started') return <Spark size={16} style={{ opacity: 0.6 }} />;
  if (status === 'failed') return <Icon name="alert-circle" size={16} color={palette.danger} />;
  return <Icon name="check" size={16} color={palette.ok} />;
}

/** What the agent did this turn, collapsed to one line; tap to see each step. */
export function ToolActivity({ activity }: { activity: Activity[] }) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
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
        <Icon name={open ? 'chevron-up' : 'chevron-down'} size={16} color={palette.textMuted} />
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
