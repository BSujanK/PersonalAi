import { useRouter } from 'expo-router';
import type { ReactNode, RefObject } from 'react';
import { RefreshControl, Text, View } from 'react-native';
import Animated, {
  Extrapolation,
  interpolate,
  useAnimatedScrollHandler,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  type SharedValue,
} from 'react-native-reanimated';
import { SafeAreaView } from 'react-native-safe-area-context';

import {
  MAX_CHROME_SCALE,
  motion,
  space,
  type,
  useTheme,
  useThemedStyles,
  type Palette,
} from '../theme';
import { GlowBackground } from './GlowBackground';
import { useTabBarSpace } from './nav/FloatingTabBar';
import { COLUMN_MAX, IconButton } from './ui';

const BAR_HEIGHT = 56;

const makeStyles = (p: Palette) => ({
  screen: { flex: 1, backgroundColor: 'transparent' },
  column: { width: '100%' as const, maxWidth: COLUMN_MAX, alignSelf: 'center' as const },
  content: { paddingHorizontal: space.md, gap: space.lg },
  bar: {
    height: BAR_HEIGHT,
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    gap: space.sm,
    paddingHorizontal: space.md - space.xs,
  },
  barSide: {
    minWidth: 44,
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    gap: space.sm,
  },
  barSideRight: { justifyContent: 'flex-end' as const },
  barTitle: { ...type.headline, flex: 1, textAlign: 'center' as const, color: p.text },
  barTitleLeft: { textAlign: 'left' as const, paddingLeft: space.xs },
  // A scroll-edge fade instead of a permanent divider: a soft band of the ink under the bar.
  edge: {
    position: 'absolute' as const,
    left: 0,
    right: 0,
    bottom: -1,
    height: 1,
    backgroundColor: p.separator,
  },
  largeTitleWrap: { paddingTop: space.xs, gap: space.xs },
  largeTitle: { ...type.display, color: p.text },
  subtitle: { ...type.subheadline, color: p.textMuted },
});

/** Pops back to where the screen was opened from. */
function BackButton() {
  const router = useRouter();
  return (
    <IconButton
      icon="chevron-left"
      glass
      label="Back"
      onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))}
    />
  );
}

/**
 * The compact navigation bar. With a `scrollY`, its title and hairline fade in as the large title
 * scrolls away. Without one, they show.
 */
export function ScreenHeader({
  title,
  back,
  left,
  right,
  scrollY,
  alignLeft,
}: {
  title: string;
  back?: boolean;
  /** Custom content on the left, e.g. an avatar and name. Replaces the title. */
  left?: ReactNode;
  right?: ReactNode;
  scrollY?: SharedValue<number>;
  alignLeft?: boolean;
}) {
  const styles = useThemedStyles(makeStyles);
  const fallback = useSharedValue(motion.titleCollapse * 2);
  const y = scrollY ?? fallback;
  // Opacity only: it reads as the title moving up into the bar, and is safe under Reduce Motion.
  const titleStyle = useAnimatedStyle(() => ({
    opacity: interpolate(
      y.get(),
      [motion.titleCollapse * 0.6, motion.titleCollapse],
      [0, 1],
      Extrapolation.CLAMP,
    ),
  }));
  const lineStyle = useAnimatedStyle(() => ({
    opacity: interpolate(y.get(), [0, space.sm], [0, 1], Extrapolation.CLAMP),
  }));
  return (
    <View style={styles.bar}>
      {back ? (
        <View style={styles.barSide}>
          <BackButton />
        </View>
      ) : null}
      {left ? (
        <View style={{ flex: 1 }}>{left}</View>
      ) : (
        <Animated.Text
          accessibilityRole="header"
          // With a large title on screen, that is the header screen readers announce.
          importantForAccessibility={scrollY ? 'no-hide-descendants' : 'auto'}
          accessibilityElementsHidden={!!scrollY}
          maxFontSizeMultiplier={MAX_CHROME_SCALE}
          numberOfLines={1}
          style={[styles.barTitle, (alignLeft || !back) && styles.barTitleLeft, titleStyle]}
        >
          {title}
        </Animated.Text>
      )}
      <View style={[styles.barSide, styles.barSideRight]}>{right}</View>
      {scrollY ? <Animated.View style={[styles.edge, lineStyle]} pointerEvents="none" /> : null}
    </View>
  );
}

/**
 * A screen over the violet glow, with a large title that collapses into the bar as the content
 * scrolls. Scroll offset lives in a shared value and only opacity and transform animate. Tab
 * screens (`tabs`) leave room at the bottom for the floating tab bar.
 */
export function Screen({
  title,
  subtitle,
  back,
  tabs,
  header,
  right,
  children,
  refreshing,
  onRefresh,
  scrollRef,
}: {
  title?: string;
  subtitle?: string;
  back?: boolean;
  /** A tab screen: content clears the floating tab bar. */
  tabs?: boolean;
  /** Custom left side of the bar (Home's avatar and name). */
  header?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  refreshing?: boolean;
  onRefresh?: () => void;
  /** For screens that scroll to one of their sections. */
  scrollRef?: RefObject<Animated.ScrollView | null>;
}) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  const reduced = useReducedMotion();
  const tabSpace = useTabBarSpace();
  const scrollY = useSharedValue(0);
  const onScroll = useAnimatedScrollHandler((e) => {
    scrollY.set(e.contentOffset.y);
  });
  const largeStyle = useAnimatedStyle(() => {
    const y = scrollY.get();
    return {
      opacity: interpolate(y, [0, motion.titleCollapse], [1, 0], Extrapolation.CLAMP),
      transform: reduced
        ? []
        : [
            { translateY: interpolate(y, [0, motion.titleCollapse], [0, -8], Extrapolation.CLAMP) },
            // Pulled down past the top it grows slightly from its leading edge, as on iOS.
            { scale: interpolate(y, [-120, 0], [1.08, 1], Extrapolation.CLAMP) },
          ],
    };
  });
  const showBar = !!(title || back || header || right);
  return (
    <View style={{ flex: 1, backgroundColor: palette.bg }}>
      <GlowBackground />
      <SafeAreaView style={styles.screen} edges={['top']}>
        {showBar ? (
          <View style={styles.column}>
            <ScreenHeader
              title={title ?? ''}
              back={back}
              left={header}
              right={right}
              scrollY={title ? scrollY : undefined}
            />
          </View>
        ) : null}
        <Animated.ScrollView
          ref={scrollRef}
          onScroll={onScroll}
          scrollEventThrottle={16}
          contentContainerStyle={[
            styles.content,
            styles.column,
            { paddingBottom: tabs ? tabSpace : space.xxl },
          ]}
          keyboardShouldPersistTaps="handled"
          refreshControl={
            onRefresh ? (
              <RefreshControl
                refreshing={refreshing ?? false}
                onRefresh={onRefresh}
                colors={[palette.accent]}
                tintColor={palette.accent}
                progressBackgroundColor={palette.raised}
              />
            ) : undefined
          }
        >
          {title && !header ? (
            <Animated.View
              style={[styles.largeTitleWrap, largeStyle, { transformOrigin: 'left center' }]}
            >
              <Text accessibilityRole="header" style={styles.largeTitle}>
                {title}
              </Text>
              {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
            </Animated.View>
          ) : null}
          {children}
        </Animated.ScrollView>
      </SafeAreaView>
    </View>
  );
}
