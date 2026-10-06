import { Text, View } from 'react-native';

import { greeting, SUGGESTIONS } from '../../lib/greeting';
import { space, type, useThemedStyles, type Palette } from '../../theme';
import { Chip } from '../ui';

const makeStyles = (p: Palette) => ({
  root: { flex: 1, justifyContent: 'center' as const, gap: space.lg, paddingBottom: space.lg },
  hello: { ...type.largeTitle, color: p.text },
  sub: { ...type.body, color: p.textMuted, marginTop: space.xs },
  chips: { gap: space.sm, alignItems: 'flex-start' as const },
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
      <View>
        <Text accessibilityRole="header" style={styles.hello}>
          {greeting(now)}
        </Text>
        <Text style={styles.sub}>What would you like to know?</Text>
      </View>
      <View style={styles.chips}>
        {SUGGESTIONS.map(({ label, prompt }) => (
          <Chip key={label} label={label} onPress={() => !disabled && onPick(prompt)} />
        ))}
      </View>
    </View>
  );
}
