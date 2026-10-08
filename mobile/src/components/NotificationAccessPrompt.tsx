import { Text, View } from 'react-native';

import { openNotificationAccessSettings } from '../lib/notificationAccess';
import { radius, space, type, useThemedStyles, type Palette } from '../theme';
import { Icon } from './Icon';
import { Button } from './ui';

const makeStyles = (p: Palette) => ({
  row: {
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    gap: space.sm + space.xs,
    paddingLeft: space.md - space.xs,
    paddingRight: space.sm,
    paddingVertical: space.sm,
    borderRadius: radius.lg,
    backgroundColor: p.accentSoft,
  },
  text: { ...type.subheadline, color: p.text, flex: 1 },
});

/**
 * A fixed note, not a modal and not dismissible, shown while payment-notification access is off.
 * Some payments arrive with no bank SMS; those are only visible through the payment apps.
 */
export function NotificationAccessPrompt() {
  const styles = useThemedStyles(makeStyles);
  return (
    <View style={styles.row}>
      <Icon name="bell-off" size={18} />
      <Text style={styles.text}>Payment app notifications are off</Text>
      <Button
        label="Turn on"
        tone="tinted"
        compact
        onPress={openNotificationAccessSettings}
        accessibilityHint="Opens Android's notification access settings"
      />
    </View>
  );
}
