import { Text, View } from 'react-native';

import type { DigestItem, InboxItem } from '../lib/api';
import { initials, rowTime } from '../lib/format';
import {
  fontFamily,
  MAX_CHROME_SCALE,
  radius,
  space,
  type,
  useTheme,
  useThemedStyles,
  type Palette,
} from '../theme';
import { Badge, PressableScale, StatusDot } from './ui';

const AVATAR = 40;

const makeStyles = (p: Palette) => ({
  card: {
    flexDirection: 'row' as const,
    gap: space.md - space.xs,
    padding: space.md - space.xs,
    borderRadius: radius.card,
    backgroundColor: p.surface,
    borderWidth: 1,
    borderColor: p.glassBorder,
  },
  avatar: {
    width: AVATAR,
    height: AVATAR,
    borderRadius: AVATAR / 2,
    backgroundColor: p.accentSoft,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
  },
  avatarText: { ...type.subheadline, fontFamily: fontFamily.bodySemiBold, color: p.accentText },
  main: { flex: 1, gap: 3 },
  top: { flexDirection: 'row' as const, alignItems: 'center' as const, gap: space.sm },
  sender: { ...type.headline, color: p.text, flexShrink: 1 },
  time: { ...type.footnote, color: p.textMuted, marginLeft: 'auto' as const },
  subject: { ...type.callout, fontFamily: fontFamily.bodyMedium, color: p.text },
  snippet: { ...type.subheadline, color: p.textMuted },
  chips: { flexDirection: 'row' as const, flexWrap: 'wrap' as const, gap: space.xs, marginTop: 2 },
});

/**
 * One mail as a tappable card: sender avatar and name, the account it arrived in, subject, a
 * one-line snippet and the time. Tapping opens the full message.
 */
export function MailCard({
  mail,
  accountLabel,
  unread,
  onPress,
}: {
  mail: DigestItem | InboxItem;
  accountLabel: string;
  unread?: boolean;
  onPress: () => void;
}) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  const sender = mail.from_name || mail.from_addr;
  const time = rowTime(mail.received);
  const subject = mail.subject || '(no subject)';
  return (
    <PressableScale
      accessibilityLabel={`${unread ? 'Unread mail' : 'Mail'} from ${sender} to ${accountLabel}: ${subject}. ${time}`}
      accessibilityHint="Opens the full message"
      onPress={onPress}
      scaleTo={0.98}
      style={styles.card}
    >
      <View style={styles.avatar}>
        <Text style={styles.avatarText} maxFontSizeMultiplier={1.3}>
          {initials(sender)}
        </Text>
      </View>
      <View style={styles.main}>
        <View style={styles.top}>
          <Text numberOfLines={1} style={styles.sender}>
            {sender}
          </Text>
          {unread ? <StatusDot color={palette.accent} /> : null}
          <Text style={styles.time} maxFontSizeMultiplier={MAX_CHROME_SCALE}>
            {time}
          </Text>
        </View>
        <Text numberOfLines={1} style={styles.subject}>
          {subject}
        </Text>
        {mail.snippet ? (
          <Text numberOfLines={1} style={styles.snippet}>
            {mail.snippet}
          </Text>
        ) : null}
        <View style={styles.chips}>
          <Badge
            label={accountLabel}
            tone="neutral"
            icon="inbox"
            spoken={`Account ${accountLabel}`}
          />
          {mail.reason ? <Badge label={mail.reason} tone="accent" /> : null}
        </View>
      </View>
    </PressableScale>
  );
}
