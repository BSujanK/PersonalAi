import { Text, type StyleProp, type TextStyle } from 'react-native';

import { MAX_CHROME_SCALE, TYPE_SCALE, familyFor, useTheme } from '../../theme';

/**
 * "PersonalAi" set as a wordmark in Newsreader, the app's editorial serif (SIL OFL). A touch
 * heavier and tighter than a title so it reads as a name, not a heading.
 */
export function Wordmark({ size = 22, style }: { size?: number; style?: StyleProp<TextStyle> }) {
  const { palette } = useTheme();
  return (
    <Text
      accessibilityRole="header"
      maxFontSizeMultiplier={MAX_CHROME_SCALE}
      numberOfLines={1}
      style={[
        {
          fontFamily: familyFor('serif', 600),
          fontSize: size,
          lineHeight: Math.round(size * 1.2),
          // Tighter than the title2 tracking at the same size: a name, set close.
          letterSpacing: TYPE_SCALE.title2.tracking - 0.2,
          color: palette.text,
        },
        style,
      ]}
    >
      PersonalAi
    </Text>
  );
}
