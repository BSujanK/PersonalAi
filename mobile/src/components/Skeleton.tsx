// Loading placeholders shaped like what is about to arrive. A group pulses as one: a single
// shared value fades every block in it together, on the UI thread.
import { useEffect, type ReactNode } from 'react';
import { View, type DimensionValue } from 'react-native';
import Animated, {
  cancelAnimation,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withRepeat,
  withTiming,
} from 'react-native-reanimated';

import {
  MIN_TARGET,
  motion,
  radius,
  space,
  timingSine,
  useThemedStyles,
  type Palette,
} from '../theme';
import { TILE } from './ui';

const AVATAR = 40;

const makeStyles = (p: Palette) => ({
  block: { backgroundColor: p.muted },
  // The same card as a ListRow (icon tile, two lines) ...
  row: {
    minHeight: MIN_TARGET + 20,
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    gap: space.md - space.xs,
    paddingHorizontal: space.md - space.xs,
    paddingVertical: space.sm + space.xs,
    backgroundColor: p.surface,
    borderRadius: radius.card,
    borderWidth: 1,
    borderColor: p.glassBorder,
  },
  // ... and as a MailCard (avatar, sender and time, subject, snippet).
  mail: {
    flexDirection: 'row' as const,
    gap: space.md - space.xs,
    padding: space.md - space.xs,
    backgroundColor: p.surface,
    borderRadius: radius.card,
    borderWidth: 1,
    borderColor: p.glassBorder,
  },
  main: { flex: 1, gap: space.sm },
  split: { flexDirection: 'row' as const, justifyContent: 'space-between' as const, gap: space.md },
  list: { gap: space.sm },
  lines: { gap: space.sm + space.xs },
});

/**
 * One pulsing placeholder. Everything inside is hidden from screen readers; the group itself
 * reads "Loading". Under Reduce Motion it stays still.
 */
export function SkeletonGroup({ children }: { children: ReactNode }) {
  const reduced = useReducedMotion();
  const pulse = useSharedValue(1);
  useEffect(() => {
    if (reduced) return;
    pulse.set(
      withRepeat(
        withTiming(motion.skeletonLow, { duration: motion.skeletonPulseMs, easing: timingSine }),
        -1,
        true,
      ),
    );
    return () => {
      cancelAnimation(pulse);
      pulse.set(1);
    };
  }, [pulse, reduced]);
  const style = useAnimatedStyle(() => ({ opacity: pulse.get() }));
  return (
    <Animated.View
      accessible
      accessibilityLabel="Loading"
      accessibilityRole="progressbar"
      style={style}
    >
      <View importantForAccessibility="no-hide-descendants" accessibilityElementsHidden>
        {children}
      </View>
    </Animated.View>
  );
}

/** A plain rounded bar. It does not pulse by itself: put it inside a SkeletonGroup. */
export function SkeletonBlock({
  width,
  height,
  radius: corner = radius.sm,
}: {
  width: DimensionValue;
  height: number;
  radius?: number;
}) {
  const styles = useThemedStyles(makeStyles);
  return <View style={[styles.block, { width, height, borderRadius: corner }]} />;
}

/** Lines of text; the last one is shorter. */
function Lines({ lines }: { lines: number }) {
  const styles = useThemedStyles(makeStyles);
  return (
    <View style={styles.lines}>
      {Array.from({ length: lines }, (_, i) => (
        <SkeletonBlock key={i} width={i === lines - 1 && lines > 1 ? '60%' : '100%'} height={12} />
      ))}
    </View>
  );
}

export function SkeletonText({ lines = 3 }: { lines?: number }) {
  return (
    <SkeletonGroup>
      <Lines lines={lines} />
    </SkeletonGroup>
  );
}

/**
 * Placeholder cards the size of the real ones, so the list does not jump when the data arrives:
 * list rows, or with `avatar` mail cards.
 */
export function SkeletonRows({ count = 3, avatar }: { count?: number; avatar?: boolean }) {
  const styles = useThemedStyles(makeStyles);
  return (
    <SkeletonGroup>
      <View style={styles.list}>
        {Array.from({ length: count }, (_, i) =>
          avatar ? (
            <View key={i} testID="skeleton-row" style={styles.mail}>
              <SkeletonBlock width={AVATAR} height={AVATAR} radius={AVATAR / 2} />
              <View style={styles.main}>
                <View style={styles.split}>
                  <SkeletonBlock width="45%" height={14} />
                  <SkeletonBlock width={36} height={12} />
                </View>
                <SkeletonBlock width="80%" height={13} />
                <SkeletonBlock width="95%" height={12} />
              </View>
            </View>
          ) : (
            <View key={i} testID="skeleton-row" style={styles.row}>
              <SkeletonBlock width={TILE} height={TILE} radius={Math.round(TILE * 0.3)} />
              <View style={styles.main}>
                <SkeletonBlock width="55%" height={14} />
                <SkeletonBlock width="35%" height={12} />
              </View>
            </View>
          ),
        )}
      </View>
    </SkeletonGroup>
  );
}
