import { Text, View } from 'react-native';
import Animated, { FadeIn, FadeOut } from 'react-native-reanimated';

import { motion, space, type, useThemedStyles, type Palette } from '../../theme';

/** The avatar's height: the status line is centred on it. */
export const THINKING_ROW_HEIGHT = 30;

// Built once: layout animations are plain config objects, never rebuilt per render. Opacity only.
const STATUS_IN = FadeIn.duration(motion.stateMs);
const STATUS_OUT = FadeOut.duration(motion.pressMs);

const makeStyles = (p: Palette) => ({
  row: { minHeight: THINKING_ROW_HEIGHT, justifyContent: 'center' as const },
  box: { paddingRight: space.sm },
  text: { ...type.body, color: p.textMuted },
  // Sizes the box so the crossfading layers can sit on top of each other without moving the row.
  sizer: { opacity: 0 },
  layer: { position: 'absolute' as const, left: 0, right: space.sm, top: 0 },
});

/**
 * The live status beside the thinking avatar ("Thinking…", "Searching the web…"). A new status
 * crossfades with the old one (opacity only, run by Reanimated on the UI thread); a screen reader
 * hears each change politely. It is only ever a verb phrase: never a tool's arguments or content.
 */
export function ThinkingStatus({ text }: { text: string }) {
  const styles = useThemedStyles(makeStyles);
  return (
    <View style={styles.row} accessibilityLiveRegion="polite">
      <View style={styles.box}>
        <Text
          numberOfLines={1}
          style={[styles.text, styles.sizer]}
          accessibilityElementsHidden
          importantForAccessibility="no-hide-descendants"
        >
          {text}
        </Text>
        <Animated.Text
          key={text}
          entering={STATUS_IN}
          exiting={STATUS_OUT}
          numberOfLines={1}
          style={[styles.text, styles.layer]}
        >
          {text}
        </Animated.Text>
      </View>
    </View>
  );
}
