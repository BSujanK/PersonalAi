// The agent's summary of a mail: a short paragraph, key points and a to-do list. Plain text only,
// like the mail body. Shown while the summary loads (as skeleton lines) and once it has arrived.
import { Text, View } from 'react-native';

import type { MailSummary } from '../lib/api';
import { summaryDueLabel } from '../lib/mailSummary';
import {
  fontFamily,
  radius,
  space,
  type,
  TYPE_SCALE,
  useThemedStyles,
  type Palette,
} from '../theme';
import { SkeletonText } from './Skeleton';
import { Badge } from './ui';

const BULLET = 5;
const CHECK = 9;

const makeStyles = (p: Palette) => ({
  card: {
    backgroundColor: p.surface,
    borderRadius: radius.card,
    borderWidth: 1,
    borderColor: p.glassBorder,
    padding: space.md,
    gap: space.md,
  },
  label: {
    flexDirection: 'row' as const,
    flexWrap: 'wrap' as const,
    alignItems: 'baseline' as const,
    gap: space.sm,
  },
  labelText: { ...type.headline, color: p.text },
  hint: { ...type.footnote, color: p.textMuted },
  text: { ...type.body, color: p.text },
  section: { gap: space.sm },
  sectionTitle: { ...type.subheadline, fontFamily: fontFamily.bodySemiBold, color: p.textMuted },
  item: { flexDirection: 'row' as const, alignItems: 'flex-start' as const, gap: space.sm + 2 },
  // The glyphs sit on the first line of text: half the line height, less half the glyph.
  bullet: {
    width: BULLET,
    height: BULLET,
    borderRadius: BULLET / 2,
    marginTop: Math.round((TYPE_SCALE.callout.lineHeight - BULLET) / 2),
    backgroundColor: p.textMuted,
  },
  check: {
    width: CHECK,
    height: CHECK,
    borderRadius: CHECK / 2,
    marginTop: Math.round((TYPE_SCALE.callout.lineHeight - CHECK) / 2),
    borderWidth: 1.5,
    borderColor: p.accent,
  },
  itemMain: { flex: 1, gap: space.xs, alignItems: 'flex-start' as const },
  itemText: { ...type.callout, color: p.text, alignSelf: 'stretch' as const },
});

/** Summary of one mail; `summary` is null while it loads. */
export function MailSummaryCard({ summary }: { summary: MailSummary | null }) {
  const styles = useThemedStyles(makeStyles);
  return (
    <View style={styles.card}>
      <View style={styles.label}>
        <Text accessibilityRole="header" style={styles.labelText}>
          Summary
        </Text>
        <Text style={styles.hint}>{summary ? 'by agent' : 'Summarising…'}</Text>
      </View>
      {summary === null ? <SkeletonText lines={4} /> : null}
      {summary?.text ? (
        <Text selectable style={styles.text}>
          {summary.text}
        </Text>
      ) : null}
      {summary && summary.points.length > 0 ? (
        <View style={styles.section}>
          {summary.points.map((point, i) => (
            <View key={`${i}:${point}`} style={styles.item}>
              <View style={styles.bullet} />
              <View style={styles.itemMain}>
                <Text selectable style={styles.itemText}>
                  {point}
                </Text>
              </View>
            </View>
          ))}
        </View>
      ) : null}
      {summary && summary.actions.length > 0 ? (
        <View style={styles.section}>
          <Text accessibilityRole="header" style={styles.sectionTitle}>
            To do
          </Text>
          {summary.actions.map((action, i) => {
            const due = summaryDueLabel(action.due);
            return (
              <View key={`${i}:${action.text}`} style={styles.item}>
                <View style={styles.check} />
                <View style={styles.itemMain}>
                  <Text selectable style={styles.itemText}>
                    {action.text}
                  </Text>
                  {due ? <Badge label={`Due ${due}`} tone="neutral" icon="calendar" /> : null}
                </View>
              </View>
            );
          })}
        </View>
      ) : null}
    </View>
  );
}
