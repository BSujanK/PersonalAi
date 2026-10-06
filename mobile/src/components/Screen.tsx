import { useNavigation, useRouter } from 'expo-router';
import type { DrawerNavigationProp } from 'expo-router/drawer';
import type { ReactNode } from 'react';
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
import { COLUMN_MAX, IconButton } from './ui';

const BAR_HEIGHT = 52;

const makeStyles = (p: Palette) => ({
  screen: { flex: 1, backgroundColor: p.bg },
  column: { width: '100%' as const, maxWidth: COLUMN_MAX, alignSelf: 'center' as const },
  content: { paddingHorizontal: space.md, paddingBottom: space.xxl, gap: space.lg },
  bar: {
    height: BAR_HEIGHT,
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    paddingHorizontal: space.xs,
    backgroundColor: p.bg,
  },
  barSide: { minWidth: 44, flexDirection: 'row' as const, alignItems: 'center' as const },
  barSideRight: { justifyContent: 'flex-end' as const },
  barTitle: { ...type.headline, flex: 1, textAlign: 'center' as const, color: p.text },
  barTitleLeft: { textAlign: 'left' as const, paddingLeft: space.sm },
  hairline: {
    position: 'absolute' as const,
    left: 0,
    right: 0,
    bottom: 0,
    height: 1,
    backgroundColor: p.separator,
  },
  largeTitleWrap: { paddingTop: space.xs, gap: space.xs },
  largeTitle: { ...type.largeTitle, color: p.text },
  subtitle: { ...type.subhead, color: p.textMuted },
});

/** Opens the drawer. Only rendered where a drawer exists (the paired app). */
function MenuButton() {
  const navigation = useNavigation<DrawerNavigationProp<Record<string, undefined>>>();
  return <IconButton icon="menu" label="Open menu" onPress={() => navigation.toggleDrawer()} />;
}

/** Pops back to where the screen was opened from. Only for screens pushed over the drawer. */
function BackButton() {
  const router = useRouter();
  return <IconButton icon="chevron-left" size={26} label="Back" onPress={() => router.back()} />;
}

/**
 * The compact navigation bar. With a `scrollY`, its title and hairline fade in as the large title
 * scrolls away (a scroll-edge effect instead of a permanent divider). Without one, they show.
 */
export function ScreenHeader({
  title,
  menu,
  back,
  right,
  scrollY,
  alignLeft,
}: {
  title: string;
  menu?: boolean;
  back?: boolean;
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
      <View style={styles.barSide}>
        {menu ? <MenuButton /> : null}
        {back ? <BackButton /> : null}
      </View>
      <Animated.Text
        accessibilityRole="header"
        // With a large title on screen, that is the header screen readers announce.
        importantForAccessibility={scrollY ? 'no-hide-descendants' : 'auto'}
        accessibilityElementsHidden={!!scrollY}
        maxFontSizeMultiplier={MAX_CHROME_SCALE}
        numberOfLines={1}
        style={[styles.barTitle, alignLeft && styles.barTitleLeft, titleStyle]}
      >
        {title}
      </Animated.Text>
      <View style={[styles.barSide, styles.barSideRight]}>{right}</View>
      <Animated.View style={[styles.hairline, lineStyle]} pointerEvents="none" />
    </View>
  );
}

/**
 * A screen with a large title that collapses into the bar as the content scrolls. Android has no
 * native large title, so this is the scroll-worklet version: scroll offset lives in a shared
 * value, and only opacity and transform animate (no layout per frame).
 */
export function Screen({
  title,
  subtitle,
  menu,
  back,
  right,
  children,
  refreshing,
  onRefresh,
}: {
  title?: string;
  subtitle?: string;
  menu?: boolean;
  back?: boolean;
  right?: ReactNode;
  children: ReactNode;
  refreshing?: boolean;
  onRefresh?: () => void;
}) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  const reduced = useReducedMotion();
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
            {
              // Pulled down past the top it grows slightly from its leading edge, as on iOS.
              scale: interpolate(y, [-120, 0], [1.08, 1], Extrapolation.CLAMP),
            },
          ],
    };
  });
  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      {title || menu || back ? (
        <View style={styles.column}>
          <ScreenHeader
            title={title ?? ''}
            menu={menu}
            back={back}
            right={right}
            scrollY={scrollY}
          />
        </View>
      ) : null}
      <Animated.ScrollView
        onScroll={onScroll}
        scrollEventThrottle={16}
        contentContainerStyle={[styles.content, styles.column]}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          onRefresh ? (
            <RefreshControl
              refreshing={refreshing ?? false}
              onRefresh={onRefresh}
              colors={[palette.accentText]}
              tintColor={palette.accentText}
              progressBackgroundColor={palette.surface}
            />
          ) : undefined
        }
      >
        {title ? (
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
  );
}
