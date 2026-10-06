import { memo, useEffect, useId, useRef } from 'react';
import { View, type StyleProp, type ViewStyle } from 'react-native';
import Animated, {
  cancelAnimation,
  useAnimatedProps,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withDelay,
  withRepeat,
  withSequence,
  withSpring,
  withTiming,
  type SharedValue,
} from 'react-native-reanimated';
import Svg, { Circle, Defs, LinearGradient, Path, Stop } from 'react-native-svg';

import { motion, timingLinear, timingSine } from '../../theme';
import { SPARK_CORE_R, SPARK_RAYS, SPARK_STOPS, SPARK_VIEWBOX } from './sparkGeometry';

const AnimatedPath = Animated.createAnimatedComponent(Path);
const RAY_COUNT = SPARK_RAYS.length;
/** One ray's share of a turn: settling to a multiple of this looks identical to the rest pose. */
const RAY_STEP = 360 / RAY_COUNT;

/**
 * - `still`: the mark, at rest.
 * - `idle`: breathes slowly (Chat's empty state).
 * - `thinking`: turns slowly while a wave runs round the rays (a reply is streaming).
 * - `intro`: rays light up one after another from a faint outline, then settle (cold launch).
 * Leaving `thinking` plays a quick settle back to the rest pose.
 */
export type SparkState = 'still' | 'idle' | 'thinking' | 'intro';

/** Gradient defs shared by every ray of one mark; each mark needs its own id. */
function useGradientId(): string {
  return `spark${useId().replace(/[^a-zA-Z0-9]/g, '')}`;
}

function Gradient({ id }: { id: string }) {
  return (
    <Defs>
      <LinearGradient id={id} gradientUnits="userSpaceOnUse" x1="10" y1="5" x2="90" y2="95">
        {SPARK_STOPS.map(([offset, stop]) => (
          <Stop key={offset} offset={offset} stopColor={stop} />
        ))}
      </LinearGradient>
    </Defs>
  );
}

/** The mark, drawn once: nine petal rays and a core, in the violet gradient or one flat colour. */
export const SparkMark = memo(function SparkMark({
  size,
  color,
}: {
  size: number;
  /** A flat colour instead of the gradient. */
  color?: string;
}) {
  const id = useGradientId();
  const fill = color ?? `url(#${id})`;
  return (
    <Svg
      width={size}
      height={size}
      viewBox={`0 0 ${SPARK_VIEWBOX} ${SPARK_VIEWBOX}`}
      accessible={false}
      importantForAccessibility="no-hide-descendants"
    >
      {color ? null : <Gradient id={id} />}
      {SPARK_RAYS.map((d) => (
        <Path key={d} d={d} fill={fill} />
      ))}
      <Circle cx={50} cy={50} r={SPARK_CORE_R} fill={fill} />
    </Svg>
  );
});

/** Ray opacity before the intro lights it; matches the faint mark on the native splash. */
const FAINT = 0.3;

/**
 * One ray whose opacity is computed on the UI thread from three shared values. The worklet
 * captures only shared values and plain numbers (`index`, `RAY_COUNT`, `FAINT`).
 */
function Ray({
  d,
  fill,
  index,
  reveal,
  phase,
  depth,
}: {
  d: string;
  fill: string;
  index: number;
  reveal: SharedValue<number>;
  phase: SharedValue<number>;
  depth: SharedValue<number>;
}) {
  const animatedProps = useAnimatedProps(() => {
    // Lit from a faint outline (the splash) as `reveal` sweeps past this ray.
    const lit = Math.min(1, Math.max(0, reveal.get() - index));
    const base = FAINT + (1 - FAINT) * lit;
    // A wave running round the rays while thinking.
    const wave = 0.5 + 0.5 * Math.sin(2 * Math.PI * (phase.get() - index / RAY_COUNT));
    return { opacity: base * (1 - depth.get() * wave) };
  });
  return <AnimatedPath d={d} fill={fill} animatedProps={animatedProps} />;
}

/** The mark, alive. Every loop runs on the UI thread; nothing here re-renders per frame. */
export function Spark({
  size,
  state = 'still',
  color,
  style,
}: {
  size: number;
  state?: SparkState;
  color?: string;
  style?: StyleProp<ViewStyle>;
}) {
  const reduced = useReducedMotion();
  const id = useGradientId();
  const fill = color ?? `url(#${id})`;
  const reveal = useSharedValue(state === 'intro' && !reduced ? 0 : RAY_COUNT);
  const phase = useSharedValue(0);
  const depth = useSharedValue(0);
  const rotate = useSharedValue(state === 'intro' && !reduced ? -RAY_STEP : 0);
  const scale = useSharedValue(state === 'intro' && !reduced ? 0.86 : 1);
  const previous = useRef<SparkState>(state);

  useEffect(() => {
    const was = previous.current;
    previous.current = state;
    cancelAnimation(phase);
    cancelAnimation(rotate);
    cancelAnimation(scale);

    if (state === 'thinking') {
      depth.set(withTiming(reduced ? 0.6 : 0.45, { duration: motion.stateMs }));
      phase.set(0);
      phase.set(
        withRepeat(withTiming(1, { duration: motion.sparkPulseMs, easing: timingLinear }), -1),
      );
      if (!reduced) {
        const from = rotate.get();
        rotate.set(
          withRepeat(
            withTiming(from + 360, { duration: motion.sparkTurnMs, easing: timingLinear }),
            -1,
          ),
        );
        scale.set(withSpring(1, { duration: motion.pressSpringMs, dampingRatio: 1 }));
      }
      return;
    }

    depth.set(withTiming(0, { duration: motion.stateMs }));
    if (reduced) {
      reveal.set(RAY_COUNT);
      rotate.set(0);
      scale.set(1);
      return;
    }

    if (state === 'intro') {
      // Rays light one after another while the mark springs up and untwists into place.
      reveal.set(withTiming(RAY_COUNT, { duration: motion.introRevealMs, easing: timingSine }));
      rotate.set(withSpring(0, { duration: motion.introRevealMs, dampingRatio: 0.7 }));
      scale.set(withSpring(1, { duration: motion.introRevealMs, dampingRatio: 0.6 }));
      return;
    }

    // Settle: come to rest on the nearest ray, so the pose matches the still mark.
    const rest = Math.round(rotate.get() / RAY_STEP) * RAY_STEP;
    rotate.set(withSpring(rest, { duration: motion.settleMs, dampingRatio: 0.7 }));
    if (was === 'thinking') {
      scale.set(
        withSequence(
          withSpring(1.1, { duration: motion.settleMs / 2, dampingRatio: 1 }),
          withSpring(1, { duration: motion.settleMs, dampingRatio: 0.6 }),
        ),
      );
    } else {
      scale.set(withSpring(1, { duration: motion.settleMs, dampingRatio: 1 }));
    }
    if (state === 'idle') {
      scale.set(
        withDelay(
          motion.settleMs,
          withRepeat(
            withTiming(1.05, { duration: motion.breatheMs, easing: timingSine }),
            -1,
            true,
          ),
        ),
      );
    }
  }, [state, reduced, depth, phase, reveal, rotate, scale]);

  const markStyle = useAnimatedStyle(() => ({
    transform: [{ rotate: `${rotate.get()}deg` }, { scale: scale.get() }],
  }));

  return (
    <Animated.View style={[style, markStyle]} accessible={false}>
      <Svg
        width={size}
        height={size}
        viewBox={`0 0 ${SPARK_VIEWBOX} ${SPARK_VIEWBOX}`}
        accessible={false}
        importantForAccessibility="no-hide-descendants"
      >
        {color ? null : <Gradient id={id} />}
        {SPARK_RAYS.map((d, i) => (
          <Ray key={d} d={d} fill={fill} index={i} reveal={reveal} phase={phase} depth={depth} />
        ))}
        <Circle cx={50} cy={50} r={SPARK_CORE_R} fill={fill} />
      </Svg>
    </Animated.View>
  );
}

/** The assistant's avatar: the spark on its own, no tile or disc behind it. */
export function SparkAvatar({ size = 32, thinking }: { size?: number; thinking?: boolean }) {
  return (
    <View style={{ width: size, height: size, alignItems: 'center', justifyContent: 'center' }}>
      <Spark size={size} state={thinking ? 'thinking' : 'still'} />
    </View>
  );
}
