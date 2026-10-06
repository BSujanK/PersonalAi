import { Text, View } from 'react-native';

import { greeting, SUGGESTIONS } from '../../lib/greeting';
import { space, type, useThemedStyles, type Palette } from '../../theme';
import type { IconName } from '../Icon';
import { Chip, Stagger } from '../ui';

/** Places the empty chat can open instead of asking the agent. */
export type EmptyTarget = 'today';

const ICONS: Record<(typeof SUGGESTIONS)[number]['label'], IconName> = {
  Emails: 'mail',
  "Today's digest": 'sun',
  News: 'globe',
  Account: 'credit-card',
  "What's due this week?": 'flag',
};

const makeStyles = (p: Palette) => ({
  root: { flex: 1, justifyContent: 'center' as const, gap: space.lg, paddingBottom: space.lg },
  hello: { ...type.display, color: p.text },
  sub: { ...type.body, color: p.textMuted, marginTop: space.xs },
  chips: { flexDirection: 'row' as const, flexWrap: 'wrap' as const, gap: space.sm },
});

/** The empty chat: a greeting and the starter chips, nothing else. */
export function EmptyState({
  onPick,
  onOpen,
  disabled,
  now,
}: {
  onPick: (text: string) => void;
  onOpen?: (target: EmptyTarget) => void;
  disabled?: boolean;
  now?: Date;
}) {
  const styles = useThemedStyles(makeStyles);
  const ask = (prompt: string) => {
    if (!disabled) onPick(prompt);
  };
  return (
    <View style={styles.root}>
      <View>
        <Text accessibilityRole="header" style={styles.hello}>
          {greeting(now)}
        </Text>
        <Text style={styles.sub}>What would you like to know?</Text>
      </View>
      <View style={styles.chips}>
        {SUGGESTIONS.map(({ label, prompt }, i) => (
          <Stagger key={label} index={i}>
            <Chip
              label={label}
              icon={ICONS[label]}
              // The digest is a screen of its own; the rest are questions for the agent.
              onPress={() => (label === "Today's digest" && onOpen ? onOpen('today') : ask(prompt))}
            />
          </Stagger>
        ))}
      </View>
    </View>
  );
}
