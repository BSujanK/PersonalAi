import { Text, View } from 'react-native';

import { greeting, SUGGESTIONS } from '../../lib/greeting';
import { fontFamily, size, useThemedStyles, type Palette } from '../../theme';
import { Chip } from '../ui';

const makeStyles = (p: Palette) => ({
  root: { flex: 1, justifyContent: 'center' as const, gap: 24, paddingBottom: 24 },
  hello: { fontFamily: fontFamily.display, fontSize: size.hero, lineHeight: 40, color: p.text },
  sub: { fontFamily: fontFamily.body, fontSize: size.body, color: p.textMuted, marginTop: 6 },
  chips: { gap: 10, alignItems: 'flex-start' as const },
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
        {SUGGESTIONS.map((text) => (
          <Chip key={text} label={text} onPress={() => !disabled && onPick(text)} />
        ))}
      </View>
    </View>
  );
}
