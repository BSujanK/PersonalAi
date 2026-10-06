import { Text, View } from 'react-native';

import { space, type, useThemedStyles, type Palette } from '../../theme';
import { Button } from '../ui';

const makeStyles = (p: Palette) => ({
  row: {
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    justifyContent: 'space-between' as const,
    gap: space.sm + space.xs,
  },
  text: { ...type.footnote, color: p.textMuted, flex: 1 },
});

/** Under an inline approval card: where the same action also waits, with a way to get there. */
export function ApprovalsHint({ onOpen }: { onOpen: () => void }) {
  const styles = useThemedStyles(makeStyles);
  return (
    <View style={styles.row}>
      <Text style={styles.text}>Waiting for your approval in Approvals</Text>
      <Button
        label="Open"
        tone="tinted"
        icon="shield"
        compact
        accessibilityLabel="Open Approvals"
        onPress={onOpen}
      />
    </View>
  );
}
