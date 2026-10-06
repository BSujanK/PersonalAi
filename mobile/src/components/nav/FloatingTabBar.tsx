import type { BottomTabBarProps } from 'expo-router/js-tabs';
import { useEffect, useState } from 'react';
import { Keyboard, Pressable, Text, View, type LayoutChangeEvent } from 'react-native';
import Animated, {
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withSpring,
} from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useAgentStatus } from '../../lib/AgentStatus';
import { haptics } from '../../lib/haptics';
import {
  fontFamily,
  MAX_CHROME_SCALE,
  motion,
  radius,
  space,
  type,
  useTheme,
  useThemedStyles,
  type Palette,
} from '../../theme';
import { Icon, type IconName } from '../Icon';

export const TAB_BAR_HEIGHT = 66;
const BAR_GAP = 10;
const PILL_INSET = 5;

/** Space a tab screen leaves at the bottom so its last row clears the floating bar. */
export function useTabBarSpace(): number {
  const insets = useSafeAreaInsets();
  return TAB_BAR_HEIGHT + BAR_GAP + Math.max(insets.bottom, space.sm) + space.md;
}

const ICONS: Record<string, IconName> = {
  index: 'message-circle',
  money: 'credit-card',
  approvals: 'shield',
};

const makeStyles = (p: Palette) => ({
  wrap: {
    position: 'absolute' as const,
    left: space.md,
    right: space.md,
    alignItems: 'center' as const,
  },
  bar: {
    width: '100%' as const,
    maxWidth: 520,
    height: TAB_BAR_HEIGHT,
    flexDirection: 'row' as const,
    borderRadius: radius.xxl + 5,
    backgroundColor: p.raised,
    borderWidth: 1,
    borderColor: p.glassBorder,
    // A soft lift off the content. Static: elevation and shadows are never animated.
    shadowColor: '#000000',
    shadowOpacity: 0.35,
    shadowRadius: 20,
    shadowOffset: { width: 0, height: 8 },
    elevation: 12,
  },
  pill: {
    position: 'absolute' as const,
    top: PILL_INSET,
    bottom: PILL_INSET,
    left: 0,
    borderRadius: radius.xxl,
    backgroundColor: p.accentStrong,
    borderWidth: 1,
    borderColor: p.accent,
  },
  item: {
    flex: 1,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
    gap: 3,
  },
  label: { ...type.caption, fontSize: 11, lineHeight: 14, fontFamily: fontFamily.bodyMedium },
  badge: {
    position: 'absolute' as const,
    top: -6,
    right: -11,
    minWidth: 18,
    height: 18,
    borderRadius: 9,
    paddingHorizontal: 4,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
    backgroundColor: p.danger,
    borderWidth: 1.5,
    borderColor: p.raised,
  },
  badgeText: {
    ...type.caption,
    fontSize: 10,
    lineHeight: 12,
    fontFamily: fontFamily.bodyBold,
    color: p.dangerOn,
  },
});

/**
 * The floating pill tab bar. Tabs are peers, so the screens switch with no animation; only the
 * violet pill moves, on a spring that carries over if a second tab is chosen mid-flight. Hidden
 * while the keyboard is up so the composer sits directly on it.
 */
export function FloatingTabBar({ state, descriptors, navigation }: BottomTabBarProps) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  const insets = useSafeAreaInsets();
  const reduced = useReducedMotion();
  const { pendingCount } = useAgentStatus();
  const [slot, setSlot] = useState(0);
  const [keyboard, setKeyboard] = useState(false);
  const x = useSharedValue(0);

  useEffect(() => {
    const show = Keyboard.addListener('keyboardDidShow', () => setKeyboard(true));
    const hide = Keyboard.addListener('keyboardDidHide', () => setKeyboard(false));
    return () => {
      show.remove();
      hide.remove();
    };
  }, []);

  useEffect(() => {
    if (slot === 0) return;
    const target = state.index * slot + PILL_INSET;
    x.set(
      reduced
        ? target
        : withSpring(target, {
            duration: motion.tabSpringMs,
            dampingRatio: motion.tabSpringDamping,
          }),
    );
  }, [state.index, slot, reduced, x]);

  // Transform only: the pill is absolute and childless, so nothing re-lays-out while it moves.
  const pillStyle = useAnimatedStyle(() => ({ transform: [{ translateX: x.get() }] }));

  const onLayout = (e: LayoutChangeEvent) => {
    const next = e.nativeEvent.layout.width / state.routes.length;
    if (Math.abs(next - slot) > 0.5) {
      x.set(state.index * next + PILL_INSET);
      setSlot(next);
    }
  };

  if (keyboard) return null;

  return (
    <View
      style={[styles.wrap, { bottom: Math.max(insets.bottom, space.sm) + BAR_GAP }]}
      pointerEvents="box-none"
    >
      <View style={styles.bar} onLayout={onLayout} accessibilityRole="tablist">
        {slot > 0 ? (
          <Animated.View
            pointerEvents="none"
            style={[styles.pill, { width: slot - PILL_INSET * 2 }, pillStyle]}
          />
        ) : null}
        {state.routes.map((route, index) => {
          const focused = state.index === index;
          const label = descriptors[route.key]?.options.title ?? route.name;
          const badge = route.name === 'approvals' && pendingCount > 0 ? pendingCount : 0;
          // Chat is home: the centre tab keeps a violet tint and a larger glyph even when idle.
          const centre = route.name === 'index';
          const color = focused
            ? palette.accentOn
            : centre
              ? palette.accentText
              : palette.textMuted;
          return (
            <Pressable
              key={route.key}
              accessibilityRole="tab"
              accessibilityState={{ selected: focused }}
              accessibilityLabel={badge ? `${label}, ${badge} pending` : label}
              onPress={() => {
                const event = navigation.emit({
                  type: 'tabPress',
                  target: route.key,
                  canPreventDefault: true,
                });
                if (focused || event.defaultPrevented) return;
                haptics.selection();
                navigation.navigate(route.name, route.params);
              }}
              onLongPress={() => navigation.emit({ type: 'tabLongPress', target: route.key })}
              style={styles.item}
            >
              <View>
                <Icon name={ICONS[route.name] ?? 'circle'} size={centre ? 25 : 21} color={color} />
                {badge ? (
                  <View style={styles.badge}>
                    <Text style={styles.badgeText} maxFontSizeMultiplier={1.2}>
                      {badge > 99 ? '99+' : badge}
                    </Text>
                  </View>
                ) : null}
              </View>
              <Text
                numberOfLines={1}
                maxFontSizeMultiplier={MAX_CHROME_SCALE}
                style={[
                  styles.label,
                  { color },
                  (focused || centre) && { fontFamily: fontFamily.bodySemiBold },
                ]}
              >
                {label}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}
