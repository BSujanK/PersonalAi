import * as Clipboard from 'expo-clipboard';
import { useEffect, useRef, useState } from 'react';
import { Text, View } from 'react-native';

import { haptics } from '../lib/haptics';
import { fontFamily, radius, space, type, useThemedStyles, type Palette } from '../theme';
import { Button } from './ui';

const COPIED_MS = 1500;

const makeStyles = (p: Palette) => ({
  wrap: { gap: space.sm },
  label: {
    ...type.footnote,
    fontFamily: fontFamily.bodySemiBold,
    letterSpacing: 0.4,
    textTransform: 'uppercase' as const,
    color: p.textMuted,
  },
  link: {
    ...type.footnote,
    fontFamily: fontFamily.mono,
    lineHeight: 19,
    color: p.accentText,
    backgroundColor: p.muted,
    borderRadius: radius.md,
    padding: space.md - space.xs,
  },
});

/**
 * A link the agent produced (e.g. a Drive share link). Shown as selectable plain text with a copy
 * button; it is never opened automatically.
 */
export function ResultLink({ link }: { link: string }) {
  const styles = useThemedStyles(makeStyles);
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);

  async function copy() {
    try {
      await Clipboard.setStringAsync(link);
      haptics.impact();
      setCopied(true);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), COPIED_MS);
    } catch {
      setCopied(false);
    }
  }

  return (
    <View style={styles.wrap}>
      <Text style={styles.label}>Share link</Text>
      <Text selectable accessibilityLabel={`Shared link: ${link}`} style={styles.link}>
        {link}
      </Text>
      <Button
        label={copied ? 'Copied' : 'Copy link'}
        icon={copied ? 'check' : 'copy'}
        tone="tinted"
        compact
        accessibilityLabel="Copy link"
        onPress={() => void copy()}
      />
    </View>
  );
}
