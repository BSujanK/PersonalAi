import { useEffect, useRef, useState } from 'react';
import { Text, View } from 'react-native';
import Animated, { FadeInDown, FadeOutDown } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { onToast } from '../lib/toast';
import { motion, radius, space, type, useThemedStyles, type Palette } from '../theme';
import { Icon } from './Icon';

const VISIBLE_MS = 2600;
// Built once at module scope; duration only (Reanimated honours Reduce Motion for layout
// animations by default, falling back to no movement).
const ENTER = FadeInDown.duration(motion.enterMs);
const EXIT = FadeOutDown.duration(Math.round(motion.enterMs * 0.8));

const makeStyles = (p: Palette) => ({
  wrap: {
    position: 'absolute' as const,
    left: space.md,
    right: space.md,
    alignItems: 'center' as const,
  },
  toast: {
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    gap: space.sm,
    paddingHorizontal: space.md,
    paddingVertical: space.sm + space.xs,
    borderRadius: radius.pill,
    backgroundColor: p.raised,
    borderWidth: 1,
    borderColor: p.border,
  },
  text: { ...type.subheadline, color: p.text },
});

/** Shows the latest toast for a moment above the tab bar. Mount once, at the root. */
export function ToastHost() {
  const styles = useThemedStyles(makeStyles);
  const insets = useSafeAreaInsets();
  const [toast, setToast] = useState<{ id: number; message: string } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    const unsubscribe = onToast((message) => {
      setToast({ id: Date.now(), message });
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setToast(null), VISIBLE_MS);
    });
    return () => {
      unsubscribe();
      clearTimeout(timer.current);
    };
  }, []);

  return (
    <View
      pointerEvents="none"
      style={[styles.wrap, { bottom: Math.max(insets.bottom, space.sm) + 104 }]}
    >
      {toast ? (
        <Animated.View
          key={toast.id}
          entering={ENTER}
          exiting={EXIT}
          style={styles.toast}
          accessibilityLiveRegion="polite"
          accessibilityRole="alert"
        >
          <Icon name="check-circle" size={16} />
          <Text style={styles.text}>{toast.message}</Text>
        </Animated.View>
      ) : null}
    </View>
  );
}
