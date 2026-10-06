import { Text, View } from 'react-native';

import { greeting, SUGGESTIONS } from '../../lib/greeting';
import { space, type, useThemedStyles, type Palette } from '../../theme';
import type { IconName } from '../Icon';
import { Spark } from '../brand/Spark';
import { Chip, Stagger } from '../ui';

const ICONS: Record<(typeof SUGGESTIONS)[number]['label'], IconName> = {
  Emails: 'mail',
  "Today's digest": 'sun',
  News: 'globe',
  Account: 'credit-card',
  "What's due this week?": 'flag',
};

const makeStyles = (p: Palette) => ({
  root: { flex: 1, justifyContent: 'center' as const, gap: space.xl, paddingBottom: space.lg },
  head: { alignItems: 'center' as const, gap: space.md },
  hello: { ...type.largeTitle, color: p.text, textAlign: 'center' as const },
  sub: { ...type.body, color: p.textMuted, textAlign: 'center' as const },
  chips: {
    flexDirection: 'row' as const,
    flexWrap: 'wrap' as const,
    justifyContent: 'center' as const,
    gap: space.sm,
  },
});

export function EmptyState({
  onPick,
  disabled,
  now,
}: {
  onPick: (text: string) => void;
  disabled?: boolean;
  now?: Date;
}) {
  const styles = useThemedStyles(makeStyles);
  return (
    <View style={styles.root}>
      <View style={styles.head}>
        <Spark size={72} />
        <View>
          <Text accessibilityRole="header" style={styles.hello}>
            {greeting(now)}
          </Text>
          <Text style={styles.sub}>What would you like to know?</Text>
        </View>
      </View>
      <View style={styles.chips}>
        {SUGGESTIONS.map(({ label, prompt }, i) => (
          <Stagger key={label} index={i}>
            <Chip label={label} icon={ICONS[label]} onPress={() => !disabled && onPick(prompt)} />
          </Stagger>
        ))}
      </View>
    </View>
  );
}
