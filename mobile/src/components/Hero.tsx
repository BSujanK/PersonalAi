import { useEffect, type ReactNode } from 'react';
import { Text, TextInput, View } from 'react-native';
import Animated, {
  useAnimatedProps,
  useReducedMotion,
  useSharedValue,
  withTiming,
} from 'react-native-reanimated';

import { formatInr } from '../lib/format';
import {
  fontFamily,
  MAX_CHROME_SCALE,
  motion,
  space,
  timingEaseOut,
  type,
  useThemedStyles,
  type Palette,
} from '../theme';
import { Icon } from './Icon';

const AnimatedTextInput = Animated.createAnimatedComponent(TextInput);

/**
 * Whole rupees with Indian digit grouping (₹12,34,567), as a worklet so the count-up formats on
 * the UI thread without a React render per frame.
 */
export function inrWhole(value: number): string {
  'worklet';
  const negative = value < 0;
  const digits = String(Math.round(Math.abs(value)));
  let out = digits.slice(-3);
  let rest = digits.slice(0, -3);
  while (rest.length > 0) {
    out = `${rest.slice(-2)},${out}`;
    rest = rest.slice(0, -2);
  }
  return `${negative ? '−' : ''}₹${out}`;
}

/**
 * A rupee figure that counts up from zero the first time it appears, then sits still. Runs on
 * the UI thread (a TextInput's text prop is the one string a worklet may set); the final value is
 * also the default text, so screen readers and the first frame without animation read it right.
 */
export function CountUp({
  value,
  style,
}: {
  /** Whole rupees. */
  value: number;
  style?: object;
}) {
  const reduced = useReducedMotion();
  const shown = useSharedValue(reduced ? value : 0);

  useEffect(() => {
    // Started from the JS thread; the worklet below only captures the shared value.
    shown.set(
      reduced ? value : withTiming(value, { duration: motion.countUpMs, easing: timingEaseOut }),
    );
  }, [value, reduced, shown]);

  const animatedProps = useAnimatedProps(() => {
    const text = inrWhole(shown.get());
    return { text, defaultValue: text } as object;
  });

  return (
    <AnimatedTextInput
      editable={false}
      underlineColorAndroid="transparent"
      accessible={false}
      importantForAccessibility="no"
      caretHidden
      defaultValue={inrWhole(value)}
      animatedProps={animatedProps}
      maxFontSizeMultiplier={MAX_CHROME_SCALE}
      style={[{ padding: 0, margin: 0, textAlign: 'center' }, style]}
    />
  );
}

const makeStyles = (p: Palette) => ({
  root: { alignItems: 'center' as const, gap: space.xs, paddingVertical: space.md },
  label: {
    ...type.subhead,
    fontFamily: fontFamily.bodyMedium,
    color: p.textMuted,
    letterSpacing: 0.2,
  },
  figure: { ...type.hero, color: p.text, minWidth: 200 },
  delta: { flexDirection: 'row' as const, alignItems: 'center' as const, gap: space.xs },
  deltaText: { ...type.footnote, fontFamily: fontFamily.bodyMedium },
});

/** The small line under the figure. `good` picks green over red; flat lines stay muted. */
export type Delta = { text: string; direction: 'up' | 'down' | 'flat'; good?: boolean };

/**
 * The hero block: a small label over one very large figure, with a small delta line under it.
 * The whole block is one accessibility element that reads the exact value.
 */
export function Hero({
  label,
  amount,
  delta,
  palette,
  footer,
}: {
  label: string;
  /** Whole rupees. */
  amount: number;
  delta?: Delta | null;
  palette: Palette;
  footer?: ReactNode;
}) {
  const styles = useThemedStyles(makeStyles);
  const color =
    !delta || delta.direction === 'flat'
      ? palette.textMuted
      : delta.good
        ? palette.ok
        : palette.danger;
  return (
    <View
      style={styles.root}
      accessible
      accessibilityRole="summary"
      accessibilityLabel={`${label}: ${formatInr(String(Math.round(amount)))}${delta ? `. ${delta.text}` : ''}`}
    >
      <Text style={styles.label} maxFontSizeMultiplier={MAX_CHROME_SCALE}>
        {label}
      </Text>
      <CountUp value={amount} style={styles.figure} />
      {delta ? (
        <View style={styles.delta}>
          {delta.direction !== 'flat' ? (
            <Icon
              name={delta.direction === 'up' ? 'trending-up' : 'trending-down'}
              size={14}
              color={color}
            />
          ) : null}
          <Text style={[styles.deltaText, { color }]} maxFontSizeMultiplier={MAX_CHROME_SCALE}>
            {delta.text}
          </Text>
        </View>
      ) : null}
      {footer}
    </View>
  );
}
