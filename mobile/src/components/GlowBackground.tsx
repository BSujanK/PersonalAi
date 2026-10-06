import { memo } from 'react';
import { StyleSheet, useWindowDimensions, View } from 'react-native';
import Svg, { Defs, Ellipse, LinearGradient, RadialGradient, Rect, Stop } from 'react-native-svg';

import { useTheme } from '../theme';

/**
 * The screen backdrop: ink at the bottom blending up into a deep violet glow at the top. A static
 * SVG gradient (no blur, nothing animated), drawn once behind the content, so it costs nothing
 * per frame on a mid-range phone.
 */
export const GlowBackground = memo(function GlowBackground({
  height,
}: {
  /** How far down the glow reaches. Defaults to about the top 60% of the screen. */
  height?: number;
}) {
  const { palette, scheme } = useTheme();
  const { height: screen } = useWindowDimensions();
  const h = height ?? Math.min(Math.round(screen * 0.62), 620);
  const strength = scheme === 'dark' ? 0.55 : 0.5;
  return (
    <View
      pointerEvents="none"
      style={[StyleSheet.absoluteFill, { backgroundColor: palette.bg }]}
      accessible={false}
      importantForAccessibility="no-hide-descendants"
    >
      <Svg width="100%" height={h} viewBox="0 0 100 100" preserveAspectRatio="none">
        <Defs>
          <LinearGradient id="wash" x1="0" y1="0" x2="0" y2="1">
            <Stop offset="0" stopColor={palette.glow} stopOpacity={1} />
            <Stop offset="1" stopColor={palette.bg} stopOpacity={1} />
          </LinearGradient>
          <RadialGradient id="bloom" cx="50%" cy="0%" rx="70%" ry="80%" fx="50%" fy="0%">
            <Stop offset="0" stopColor={palette.accentStrong} stopOpacity={strength} />
            <Stop offset="0.55" stopColor={palette.accentStrong} stopOpacity={strength * 0.25} />
            <Stop offset="1" stopColor={palette.accentStrong} stopOpacity={0} />
          </RadialGradient>
        </Defs>
        <Rect x="0" y="0" width="100" height="100" fill="url(#wash)" />
        <Ellipse cx="50" cy="0" rx="85" ry="75" fill="url(#bloom)" />
      </Svg>
    </View>
  );
});
