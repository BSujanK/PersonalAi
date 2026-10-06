import { memo, useId } from 'react';
import { View, type StyleProp, type ViewStyle } from 'react-native';
import Animated, { useReducedMotion } from 'react-native-reanimated';
import Svg, { Circle, Defs, LinearGradient, Path, Stop } from 'react-native-svg';

import { motion, useThemedStyles, type Palette } from '../../theme';
import { SPARK_CORE_R, SPARK_RAYS, SPARK_STOPS, SPARK_VIEWBOX } from './sparkGeometry';

// Loops are Reanimated CSS animations: they run on the UI thread and need no shared value.
// Keyframes live at module scope so they are built once.
const TURN = {
  from: { transform: [{ rotate: '0deg' }] },
  to: { transform: [{ rotate: '360deg' }] },
} as const;

const BREATHE = {
  '0%': { opacity: 0.6, transform: [{ scale: 0.9 }] },
  '50%': { opacity: 1, transform: [{ scale: 1.05 }] },
  '100%': { opacity: 0.6, transform: [{ scale: 0.9 }] },
} as const;

// Reduce Motion keeps the "still working" signal but drops rotation and scale.
const BREATHE_REDUCED = {
  '0%': { opacity: 0.45 },
  '50%': { opacity: 1 },
  '100%': { opacity: 0.45 },
} as const;

/** The mark itself: nine petal rays and a core, in the violet gradient (or one flat colour). */
export const SparkMark = memo(function SparkMark({
  size,
  color,
}: {
  size: number;
  /** A flat colour instead of the gradient, e.g. white on a violet tile. */
  color?: string;
}) {
  // Each mark needs its own gradient id; two marks on screen must not share one.
  const id = `spark${useId().replace(/[^a-zA-Z0-9]/g, '')}`;
  const fill = color ?? `url(#${id})`;
  return (
    <Svg
      width={size}
      height={size}
      viewBox={`0 0 ${SPARK_VIEWBOX} ${SPARK_VIEWBOX}`}
      accessible={false}
      importantForAccessibility="no-hide-descendants"
    >
      {color ? null : (
        <Defs>
          <LinearGradient id={id} gradientUnits="userSpaceOnUse" x1="10" y1="5" x2="90" y2="95">
            {SPARK_STOPS.map(([offset, stop]) => (
              <Stop key={offset} offset={offset} stopColor={stop} />
            ))}
          </LinearGradient>
        </Defs>
      )}
      {SPARK_RAYS.map((d) => (
        <Path key={d} d={d} fill={fill} />
      ))}
      <Circle cx={50} cy={50} r={SPARK_CORE_R} fill={fill} />
    </Svg>
  );
});

/**
 * The spark, optionally alive. `thinking` turns it slowly and lets it breathe while a reply
 * streams; with Reduce Motion it only fades in and out.
 */
export function Spark({
  size,
  thinking,
  color,
  style,
}: {
  size: number;
  thinking?: boolean;
  color?: string;
  style?: StyleProp<ViewStyle>;
}) {
  const reduced = useReducedMotion();
  if (!thinking) {
    return (
      <View style={style}>
        <SparkMark size={size} color={color} />
      </View>
    );
  }
  return (
    <Animated.View
      style={[
        style,
        {
          animationName: reduced ? BREATHE_REDUCED : BREATHE,
          animationDuration: motion.sparkPulseMs,
          animationIterationCount: 'infinite',
          animationTimingFunction: 'ease-in-out',
        },
      ]}
    >
      <Animated.View
        style={
          reduced
            ? undefined
            : {
                animationName: TURN,
                animationDuration: motion.sparkTurnMs,
                animationIterationCount: 'infinite',
                animationTimingFunction: 'linear',
              }
        }
      >
        <SparkMark size={size} color={color} />
      </Animated.View>
    </Animated.View>
  );
}

const makeStyles = (p: Palette) => ({
  tile: {
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
    backgroundColor: p.accentSoft,
    borderWidth: 1,
    borderColor: p.glassBorder,
  },
});

/** The assistant's avatar: the spark on a round violet-tinted tile. */
export function SparkAvatar({ size = 32, thinking }: { size?: number; thinking?: boolean }) {
  const styles = useThemedStyles(makeStyles);
  return (
    <View
      style={[styles.tile, { width: size, height: size, borderRadius: size / 2 }]}
      accessible={false}
    >
      <Spark size={size * 0.72} thinking={thinking} />
    </View>
  );
}
