import { Text, View } from 'react-native';

import { greeting, SUGGESTIONS } from '../../lib/greeting';
import type { SpendHero } from '../../lib/spend';
import { space, type, useTheme, useThemedStyles, type Palette } from '../../theme';
import { Spark } from '../brand/Spark';
import { Hero } from '../Hero';
import type { IconName } from '../Icon';
import { QuickAccess, type QuickItem } from '../QuickAccess';
import { Chip, Stagger } from '../ui';

/** Places the empty chat can open instead of asking the agent. */
export type EmptyTarget = 'today' | 'mail' | 'calendar' | 'files';

const ICONS: Record<(typeof SUGGESTIONS)[number]['label'], IconName> = {
  Emails: 'mail',
  "Today's digest": 'sun',
  News: 'globe',
  Account: 'credit-card',
  "What's due this week?": 'flag',
};

const NEWS = SUGGESTIONS.find((s) => s.label === 'News')?.prompt ?? '';

const makeStyles = (p: Palette) => ({
  root: { flex: 1, justifyContent: 'center' as const, gap: space.lg, paddingBottom: space.lg },
  head: { flexDirection: 'row' as const, alignItems: 'center' as const, gap: space.md },
  headText: { flex: 1 },
  hello: { ...type.title1, color: p.text },
  sub: { ...type.callout, color: p.textMuted, marginTop: 2 },
  chips: { flexDirection: 'row' as const, flexWrap: 'wrap' as const, gap: space.sm },
});

/**
 * Chat is home, so the empty chat carries what Home used to: today's spend, Quick Access cards
 * and the starter chips. The spark breathes here while nothing is happening.
 */
export function EmptyState({
  onPick,
  onOpen,
  spend,
  disabled,
  now,
}: {
  onPick: (text: string) => void;
  onOpen?: (target: EmptyTarget) => void;
  /** undefined while loading; null when money is not set up. */
  spend?: SpendHero | null;
  disabled?: boolean;
  now?: Date;
}) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  const ask = (prompt: string) => {
    if (!disabled) onPick(prompt);
  };
  const quick: QuickItem[] = [
    {
      key: 'mail',
      icon: 'mail',
      title: 'Mail',
      detail: 'Inbox',
      onPress: () => onOpen?.('mail'),
      accessibilityHint: 'Opens Today at your mail',
    },
    {
      key: 'calendar',
      icon: 'calendar',
      title: 'Calendar',
      detail: 'Events',
      onPress: () => onOpen?.('calendar'),
      accessibilityHint: 'Opens Today at your events',
    },
    {
      key: 'files',
      icon: 'folder',
      title: 'Files',
      detail: 'Laptop · Drive',
      onPress: () => onOpen?.('files'),
    },
    {
      key: 'news',
      icon: 'globe',
      title: 'News',
      detail: 'Headlines',
      onPress: () => ask(NEWS),
      accessibilityHint: 'Asks the agent for the headlines',
    },
  ];
  return (
    <View style={styles.root}>
      <View style={styles.head}>
        <Spark size={52} state="idle" />
        <View style={styles.headText}>
          <Text accessibilityRole="header" style={styles.hello}>
            {greeting(now)}
          </Text>
          <Text style={styles.sub}>What would you like to know?</Text>
        </View>
      </View>
      {spend !== undefined ? (
        <Hero
          label={spend?.label ?? 'Spent today'}
          amount={spend?.amount ?? 0}
          delta={spend ? spend.delta : { text: 'Money is not set up yet', direction: 'flat' }}
          palette={palette}
        />
      ) : null}
      <QuickAccess items={quick} />
      <View style={styles.chips}>
        {SUGGESTIONS.map(({ label, prompt }, i) => (
          <Stagger key={label} index={i}>
            <Chip
              label={label}
              icon={ICONS[label]}
              // The digest is a screen of its own; the rest are questions for the agent.
              onPress={() =>
                label === "Today's digest" && onOpen ? onOpen('today') : ask(prompt)
              }
            />
          </Stagger>
        ))}
      </View>
    </View>
  );
}
