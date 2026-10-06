import * as Clipboard from 'expo-clipboard';
import { useState } from 'react';
import { Text, View } from 'react-native';

import { fontFamily, size, useThemedStyles, type Palette } from '../theme';
import { Button } from './ui';

const makeStyles = (p: Palette) => ({
  wrap: { gap: 8 },
  link: {
    fontFamily: fontFamily.mono,
    fontSize: size.small,
    lineHeight: 20,
    color: p.text,
    backgroundColor: p.muted,
    borderRadius: 10,
    padding: 12,
  },
});

/**
 * A link the agent produced (e.g. a Drive share link). Shown as selectable plain text with a copy
 * button; it is never opened automatically.
 */
export function ResultLink({ link }: { link: string }) {
  const styles = useThemedStyles(makeStyles);
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await Clipboard.setStringAsync(link);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <View style={styles.wrap}>
      <Text selectable accessibilityLabel="Shared link" style={styles.link}>
        {link}
      </Text>
      <Button
        label={copied ? 'Copied' : 'Copy link'}
        tone="plain"
        accessibilityLabel="Copy link"
        onPress={() => void copy()}
      />
    </View>
  );
}
