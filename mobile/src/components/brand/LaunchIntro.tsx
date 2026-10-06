import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { Pressable, StyleSheet, useWindowDimensions, View } from 'react-native';
import Animated, {
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withSequence,
  withSpring,
  withTiming,
  type SharedValue,
} from 'react-native-reanimated';
import Svg, { Defs, RadialGradient, Rect, Stop } from 'react-native-svg';

import { motion, timingEaseOut, timingSine, useTheme } from '../../theme';
import { Spark } from './Spark';

/**
 * Full size of the mark in the intro (at scale 1). The native splash (expo-splash-screen
 * imageWidth 160, mark drawn at 90% of its canvas) shows it at the intro's starting pose: 60%
 * size, turned back 1.15 turns, faint. So the hand-off from the native splash shows no jump.
 */
export const INTRO_SIZE = 144;

// Module state survives while the JS runtime does: a warm start (back from the background, or the
// activity recreated in the same process) never replays the intro. Only a cold launch does.
let introPlayed = false;

/** Test hook: lets each test start from a cold launch. */
export function resetIntroForTests(): void {
  introPlayed = false;
}

interface Intro {
  /** True while the intro covers the app; the header mark stays hidden until it lands. */
  active: boolean;
  /** Where the header mark sits on screen, so the intro can glide into it. */
  setTarget: (x: number, y: number, size: number) => void;
}

const IntroContext = createContext<Intro>({ active: false, setTarget: () => undefined });

export const useIntro = () => useContext(IntroContext);

/**
 * Plays the cold-launch intro over the app: the spark spins in (about 1.15 turns, settling on a
 * spring) while it scales from 60% to full size, fades and glows in, then shrinks and glides into
 * its place at the left of the Chat header while Chat fades in underneath. Transform and opacity only, on the UI thread; a tap skips
 * it. With Reduce Motion it is the still mark and a short fade.
 */
export function IntroProvider({ children }: { children: ReactNode }) {
  const [active, setActive] = useState(() => !introPlayed);
  const tx = useSharedValue(-1);
  const ty = useSharedValue(-1);
  const tsize = useSharedValue(-1);

  useEffect(() => {
    introPlayed = true;
  }, []);

  const setTarget = useCallback(
    (x: number, y: number, size: number) => {
      tx.set(x);
      ty.set(y);
      tsize.set(size);
    },
    [tx, ty, tsize],
  );

  const value = useMemo(() => ({ active, setTarget }), [active, setTarget]);
  return (
    <IntroContext.Provider value={value}>
      {children}
      {active ? <IntroOverlay target={{ tx, ty, tsize }} onDone={() => setActive(false)} /> : null}
    </IntroContext.Provider>
  );
}

function IntroOverlay({
  target,
  onDone,
}: {
  target: { tx: SharedValue<number>; ty: SharedValue<number>; tsize: SharedValue<number> };
  onDone: () => void;
}) {
  const { palette } = useTheme();
  const reduced = useReducedMotion();
  const { width, height } = useWindowDimensions();
  const backdrop = useSharedValue(1);
  const glow = useSharedValue(0);
  const glowScale = useSharedValue(0.8);
  const x = useSharedValue(0);
  const y = useSharedValue(0);
  const scale = useSharedValue(1);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const finished = useRef(false);

  const finish = useCallback(() => {
    if (finished.current) return;
    finished.current = true;
    timers.current.forEach(clearTimeout);
    onDone();
  }, [onDone]);

  useEffect(() => {
    const later = (ms: number, run: () => void) => timers.current.push(setTimeout(run, ms));
    if (reduced) {
      later(motion.introFadeMs, () =>
        backdrop.set(withTiming(0, { duration: motion.introFadeMs, easing: timingEaseOut })),
      );
      later(motion.introFadeMs * 2, finish);
      return () => timers.current.forEach(clearTimeout);
    }

    // The glow swells as the last rays light, then eases back.
    later(motion.introSpinMs * 0.35, () => {
      glow.set(
        withSequence(
          withTiming(0.9, { duration: motion.introGlowMs / 2, easing: timingSine }),
          withTiming(0.35, { duration: motion.introGlowMs / 2, easing: timingSine }),
        ),
      );
      glowScale.set(withTiming(1.25, { duration: motion.introGlowMs, easing: timingSine }));
    });

    const glideAt = motion.introSpinMs + motion.introGlowMs * 0.3;
    later(glideAt, () => {
      const size = target.tsize.get();
      const spring = { duration: motion.introGlideMs, dampingRatio: 1 };
      if (size > 0) {
        // Centre of the header mark, relative to the centre of the screen.
        x.set(withSpring(target.tx.get() + size / 2 - width / 2, spring));
        y.set(withSpring(target.ty.get() + size / 2 - height / 2, spring));
        scale.set(withSpring(size / INTRO_SIZE, spring));
      } else {
        // No header on screen (pairing): fade in place.
        scale.set(withSpring(0.9, spring));
      }
      glow.set(withTiming(0, { duration: motion.introGlideMs, easing: timingEaseOut }));
      backdrop.set(withTiming(0, { duration: motion.introGlideMs, easing: timingEaseOut }));
    });
    later(glideAt + motion.introGlideMs, finish);
    return () => timers.current.forEach(clearTimeout);
  }, [reduced, width, height, target, backdrop, glow, glowScale, x, y, scale, finish]);

  const backdropStyle = useAnimatedStyle(() => ({ opacity: backdrop.get() }));
  const glowStyle = useAnimatedStyle(() => ({
    opacity: glow.get(),
    transform: [{ scale: glowScale.get() }],
  }));
  const markStyle = useAnimatedStyle(() => ({
    transform: [{ translateX: x.get() }, { translateY: y.get() }, { scale: scale.get() }],
  }));
  // Without a target the mark fades with the backdrop instead of landing anywhere.
  const markFade = useAnimatedStyle(() => ({
    opacity: target.tsize.get() > 0 ? 1 : backdrop.get(),
  }));

  const skip = () => {
    if (finished.current) return;
    timers.current.forEach(clearTimeout);
    backdrop.set(withTiming(0, { duration: motion.stateMs }));
    glow.set(withTiming(0, { duration: motion.stateMs }));
    timers.current = [setTimeout(finish, motion.stateMs)];
  };

  const glowSize = INTRO_SIZE * 2.4;
  return (
    <Pressable
      style={StyleSheet.absoluteFill}
      onPress={skip}
      accessibilityRole="button"
      accessibilityLabel="Skip intro"
      testID="launch-intro"
    >
      <Animated.View
        pointerEvents="none"
        style={[StyleSheet.absoluteFill, { backgroundColor: palette.bg }, backdropStyle]}
      />
      <View pointerEvents="none" style={styles.center}>
        <Animated.View style={[{ position: 'absolute' }, glowStyle]}>
          <Svg width={glowSize} height={glowSize}>
            <Defs>
              <RadialGradient id="introGlow" cx="50%" cy="50%" r="50%">
                <Stop offset="0" stopColor={palette.accent} stopOpacity={0.55} />
                <Stop offset="0.6" stopColor={palette.accentStrong} stopOpacity={0.12} />
                <Stop offset="1" stopColor={palette.accentStrong} stopOpacity={0} />
              </RadialGradient>
            </Defs>
            <Rect width={glowSize} height={glowSize} fill="url(#introGlow)" />
          </Svg>
        </Animated.View>
        <Animated.View style={[markStyle, markFade]}>
          <Spark size={INTRO_SIZE} state={reduced ? 'still' : 'intro'} />
        </Animated.View>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  center: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
