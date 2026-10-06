// The app's component kit. Dark glass and violet: every list row is its own rounded card, icons
// sit on soft tiles, buttons are pills, and one violet carries every active state. Press feedback
// is a critically damped spring on the UI thread, felt more than seen (scale 0.97, ~120 ms).
import { Children, isValidElement, useMemo, type ReactNode } from 'react';
import {
  ActivityIndicator,
  Pressable,
  Text,
  TextInput,
  View,
  type AccessibilityActionEvent,
  type AccessibilityActionInfo,
  type AccessibilityRole,
  type Insets,
  type StyleProp,
  type TextInputProps,
  type ViewStyle,
} from 'react-native';
import Animated, {
  FadeInDown,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withSpring,
} from 'react-native-reanimated';

import { haptics } from '../lib/haptics';
import {
  easeOut,
  fontFamily,
  MAX_CHROME_SCALE,
  MIN_TARGET,
  motion,
  radius,
  space,
  type,
  useTheme,
  useThemedStyles,
} from '../theme';
import type { Palette } from '../theme';
import { Icon, type IconName } from './Icon';

/** Readable column: full width on a phone, capped and centred on wider screens. */
export const COLUMN_MAX = 720;

/** Icon tiles on list cards. */
export const TILE = 40;

const HIT_SLOP: Insets = { top: 8, bottom: 8, left: 8, right: 8 };

const makeStyles = (p: Palette) => ({
  iconButton: {
    width: MIN_TARGET,
    height: MIN_TARGET,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
    borderRadius: MIN_TARGET / 2,
  },
  glassButton: {
    backgroundColor: p.glass,
    borderWidth: 1,
    borderColor: p.glassBorder,
  },
  badgeDot: {
    position: 'absolute' as const,
    top: 10,
    right: 11,
    width: 9,
    height: 9,
    borderRadius: 5,
    borderWidth: 1.5,
    borderColor: p.bg,
    backgroundColor: p.accent,
  },
  title: { ...type.title1, color: p.text },
  section: { ...type.title3, color: p.text },
  card: {
    backgroundColor: p.surface,
    borderRadius: radius.card,
    borderWidth: 1,
    borderColor: p.glassBorder,
    padding: space.md,
    gap: space.sm,
  },
  body: { ...type.body, color: p.text },
  caption: { ...type.footnote, color: p.textMuted },
  muted: { color: p.textMuted },
  error: { ...type.subheadline, color: p.danger },
  button: {
    borderRadius: radius.pill,
    minHeight: 52,
    paddingVertical: space.sm + space.xs,
    paddingHorizontal: space.lg - space.xs,
    flexDirection: 'row' as const,
    gap: space.sm,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
    borderWidth: 1,
    borderColor: 'transparent',
  },
  buttonCompact: { minHeight: MIN_TARGET, paddingVertical: space.sm, paddingHorizontal: space.md },
  buttonText: { ...type.headline },
  chip: {
    minHeight: 38,
    justifyContent: 'center' as const,
    paddingHorizontal: space.md,
    borderRadius: radius.pill,
    backgroundColor: p.glass,
    borderWidth: 1,
    borderColor: p.glassBorder,
  },
  chipOn: { backgroundColor: p.accentStrong, borderColor: p.accent },
  chipText: { ...type.subheadline, fontFamily: fontFamily.bodyMedium, color: p.text },
  chipTextOn: { color: p.accentOn, fontFamily: fontFamily.bodySemiBold },
  input: {
    ...type.body,
    minHeight: MIN_TARGET + 4,
    borderRadius: radius.lg,
    paddingHorizontal: space.md,
    paddingVertical: space.sm + space.xs,
    backgroundColor: p.surface,
    borderWidth: 1,
    borderColor: p.border,
    color: p.text,
  },
  searchWrap: { justifyContent: 'center' as const },
  searchInput: { paddingLeft: space.xl + space.sm, borderRadius: radius.pill },
  searchIcon: { position: 'absolute' as const, left: space.md },
  loading: { marginVertical: space.lg },
  failed: {
    alignItems: 'center' as const,
    gap: space.xs,
    padding: space.lg,
    backgroundColor: p.surface,
    borderRadius: radius.card,
    borderWidth: 1,
    borderColor: p.glassBorder,
  },
  failedTitle: { ...type.headline, color: p.text, textAlign: 'center' as const },
  failedLine: { ...type.subheadline, color: p.textMuted, textAlign: 'center' as const },
  failedReason: { ...type.footnote, color: p.textMuted, textAlign: 'center' as const },
  stale: { ...type.footnote, color: p.textMuted, paddingHorizontal: space.xs },
  // Card lists
  sectionHead: {
    flexDirection: 'row' as const,
    alignItems: 'baseline' as const,
    justifyContent: 'space-between' as const,
    gap: space.sm,
    paddingHorizontal: space.xs,
    paddingBottom: space.sm + space.xs,
  },
  sectionAction: { ...type.subheadline, fontFamily: fontFamily.bodyMedium, color: p.accentText },
  sectionFooter: {
    ...type.footnote,
    color: p.textMuted,
    paddingHorizontal: space.xs,
    paddingTop: space.sm + space.xs,
  },
  cards: { gap: space.sm },
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
  rowSelected: { borderColor: p.accent },
  rowMain: { flex: 1, gap: 3 },
  rowTitle: { ...type.callout, fontFamily: fontFamily.bodySemiBold, color: p.text },
  rowTitleStrong: { fontFamily: fontFamily.bodyBold },
  rowSubtitle: { ...type.footnote, color: p.textMuted },
  rowTrail: {
    alignItems: 'flex-end' as const,
    gap: space.xs,
    flexShrink: 0,
    maxWidth: '50%' as const,
  },
  rowValueLine: { flexDirection: 'row' as const, alignItems: 'center' as const, gap: 6 },
  rowValue: { ...type.number, color: p.text },
  rowValueMuted: { ...type.footnote, color: p.textMuted },
  rowMeta: { alignItems: 'flex-end' as const, gap: space.xs, flexShrink: 0 },
  iconTile: {
    width: TILE,
    height: TILE,
    borderRadius: radius.md,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
    backgroundColor: p.muted,
  },
  dot: { width: 8, height: 8, borderRadius: 4 },
  emptyRow: {
    ...type.subheadline,
    color: p.textMuted,
    padding: space.md,
    backgroundColor: p.surface,
    borderRadius: radius.card,
    borderWidth: 1,
    borderColor: p.glassBorder,
    overflow: 'hidden' as const,
  },
  // Badges
  badge: {
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    gap: 3,
    alignSelf: 'flex-start' as const,
    paddingHorizontal: space.sm,
    paddingVertical: 2,
    borderRadius: radius.pill,
  },
  badgeText: {
    ...type.caption,
    fontFamily: fontFamily.bodyBold,
    letterSpacing: 0.4,
  },
  // Notice
  notice: {
    flexDirection: 'row' as const,
    gap: space.sm + space.xs,
    padding: space.md - space.xs,
    borderRadius: radius.lg,
  },
  noticeMain: { flex: 1, gap: 2 },
  noticeTitle: { ...type.subheadline, fontFamily: fontFamily.bodySemiBold },
  noticeBody: { ...type.subheadline },
  // Segmented control
  segmented: {
    flexDirection: 'row' as const,
    backgroundColor: p.glass,
    borderWidth: 1,
    borderColor: p.glassBorder,
    borderRadius: radius.pill,
    padding: 3,
  },
  segment: {
    flex: 1,
    minHeight: MIN_TARGET - 6,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
    borderRadius: radius.pill,
    paddingHorizontal: space.sm,
    backgroundColor: 'transparent',
    transitionProperty: 'backgroundColor',
    transitionDuration: motion.stateMs,
    transitionTimingFunction: easeOut,
  },
  segmentOn: { backgroundColor: p.accentStrong },
  segmentText: { ...type.subheadline, fontFamily: fontFamily.bodyMedium, color: p.textMuted },
  segmentTextOn: { fontFamily: fontFamily.bodySemiBold, color: p.accentOn },
});

type A11y = {
  accessibilityActions?: AccessibilityActionInfo[];
  onAccessibilityAction?: (event: AccessibilityActionEvent) => void;
  accessibilityLabel?: string;
  accessibilityHint?: string;
  accessibilityRole?: AccessibilityRole;
  accessibilityState?: { disabled?: boolean; selected?: boolean; expanded?: boolean };
};

/**
 * The one pressable: feedback on press-in, commit on press-out. The scale is a critically damped
 * spring on the UI thread, so a press released mid-way reverses from where it is instead of
 * restarting. With Reduce Motion on, it dims instead of scaling.
 */
export function PressableScale({
  children,
  onPress,
  onLongPress,
  disabled,
  style,
  hitSlop,
  dim,
  scaleTo = motion.pressScale,
  testID,
  ...a11y
}: A11y & {
  children: ReactNode;
  onPress?: () => void;
  onLongPress?: () => void;
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
  hitSlop?: Insets | number;
  /** Dim instead of scaling. */
  dim?: boolean;
  /** Pressed scale; large cards use `motion.pressScaleCard`. */
  scaleTo?: number;
  testID?: string;
}) {
  const reduced = useReducedMotion();
  const scale = useSharedValue(1);
  const opacity = useSharedValue(1);
  const fade = dim || reduced;
  // The worklet captures shared values only; spring configs are built from plain numbers below.
  const animated = useAnimatedStyle(() => ({
    transform: [{ scale: scale.get() }],
    opacity: opacity.get(),
  }));
  const springTo = (to: number) =>
    withSpring(to, { duration: motion.pressSpringMs, dampingRatio: motion.pressSpringDamping });
  return (
    <Pressable
      accessibilityRole={a11y.accessibilityRole ?? 'button'}
      accessibilityLabel={a11y.accessibilityLabel}
      accessibilityHint={a11y.accessibilityHint}
      accessibilityState={{ ...a11y.accessibilityState, disabled: !!disabled }}
      accessibilityActions={a11y.accessibilityActions}
      onAccessibilityAction={a11y.onAccessibilityAction}
      onPress={onPress}
      onLongPress={onLongPress}
      delayLongPress={onLongPress ? 350 : undefined}
      onPressIn={() => {
        if (fade) opacity.set(springTo(0.6));
        else scale.set(springTo(scaleTo));
      }}
      onPressOut={() => {
        opacity.set(springTo(1));
        scale.set(springTo(1));
      }}
      disabled={disabled}
      hitSlop={hitSlop}
      pressRetentionOffset={16}
      testID={testID}
    >
      <Animated.View style={[style, animated, disabled && { opacity: 0.4 }]}>
        {children}
      </Animated.View>
    </Pressable>
  );
}

export function IconButton({
  icon,
  label,
  onPress,
  disabled,
  color,
  size = 22,
  glass,
  badge,
}: {
  icon: IconName;
  label: string;
  onPress: () => void;
  disabled?: boolean;
  color?: string;
  size?: number;
  /** A round glass button, for screen headers over the glow. */
  glass?: boolean;
  /** A small violet dot on the button, e.g. new alerts. */
  badge?: boolean;
}) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  return (
    <PressableScale
      accessibilityLabel={label}
      onPress={onPress}
      disabled={disabled}
      hitSlop={4}
      style={[styles.iconButton, glass && styles.glassButton]}
    >
      <Icon
        name={icon}
        size={glass ? 20 : size}
        color={color ?? (glass ? palette.text : palette.accentText)}
      />
      {badge ? <View style={styles.badgeDot} /> : null}
    </PressableScale>
  );
}

export function Title({ children }: { children: ReactNode }) {
  const styles = useThemedStyles(makeStyles);
  return (
    <Text accessibilityRole="header" style={styles.title}>
      {children}
    </Text>
  );
}

export function SectionTitle({ children }: { children: ReactNode }) {
  const styles = useThemedStyles(makeStyles);
  return (
    <Text
      accessibilityRole="header"
      maxFontSizeMultiplier={MAX_CHROME_SCALE}
      style={styles.section}
    >
      {children}
    </Text>
  );
}

export function Card({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  const styles = useThemedStyles(makeStyles);
  return <View style={[styles.card, style]}>{children}</View>;
}

export function Body({ children, muted }: { children: ReactNode; muted?: boolean }) {
  const styles = useThemedStyles(makeStyles);
  return <Text style={[styles.body, muted && styles.muted]}>{children}</Text>;
}

export function Caption({ children }: { children: ReactNode }) {
  const styles = useThemedStyles(makeStyles);
  return <Text style={styles.caption}>{children}</Text>;
}

export function ErrorText({ message }: { message: string | null }) {
  const styles = useThemedStyles(makeStyles);
  return message ? (
    <Text accessibilityRole="alert" style={styles.error}>
      {message}
    </Text>
  ) : null;
}

export type ButtonTone = 'primary' | 'tinted' | 'plain' | 'danger' | 'dangerTinted';

function buttonColors(p: Palette, tone: ButtonTone): { bg: string; fg: string; edge: string } {
  switch (tone) {
    case 'primary':
      // The deep violet carries white text at 7.1:1; the bright violet edge is the highlight.
      return { bg: p.accentStrong, fg: p.accentOn, edge: p.accent };
    case 'tinted':
      return { bg: p.accentSoft, fg: p.accentText, edge: p.accentSoft };
    case 'plain':
      return { bg: p.glass, fg: p.text, edge: p.glassBorder };
    case 'danger':
      return { bg: p.danger, fg: p.dangerOn, edge: p.danger };
    case 'dangerTinted':
      return { bg: p.dangerSoft, fg: p.danger, edge: p.dangerSoft };
  }
}

export function Button({
  label,
  onPress,
  disabled,
  tone = 'primary',
  icon,
  compact,
  trailing,
  accessibilityLabel,
  accessibilityHint,
}: {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  tone?: ButtonTone;
  icon?: IconName;
  compact?: boolean;
  /** Extra content after the label, e.g. a count. */
  trailing?: ReactNode;
  accessibilityLabel?: string;
  accessibilityHint?: string;
}) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  const { bg, fg, edge } = buttonColors(palette, tone);
  return (
    <PressableScale
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityHint={accessibilityHint}
      onPress={onPress}
      disabled={disabled}
      style={[
        styles.button,
        compact && styles.buttonCompact,
        { backgroundColor: bg, borderColor: edge },
        tone === 'primary' && {
          // A violet glow under the filled pill. Static: elevation is never animated.
          shadowColor: palette.accent,
          shadowOpacity: 0.4,
          shadowRadius: 16,
          shadowOffset: { width: 0, height: 6 },
          elevation: 6,
        },
      ]}
    >
      {icon ? <Icon name={icon} size={18} color={fg} /> : null}
      <Text numberOfLines={1} style={[styles.buttonText, { color: fg }]}>
        {label}
      </Text>
      {trailing}
    </PressableScale>
  );
}

/** A tappable pill: filter, suggestion or choice. `selected` marks the active choice. */
export function Chip({
  label,
  onPress,
  selected,
  icon,
  accessibilityLabel,
}: {
  label: string;
  onPress: () => void;
  selected?: boolean;
  icon?: IconName;
  accessibilityLabel?: string;
}) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  return (
    <PressableScale
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityState={{ selected: !!selected }}
      onPress={onPress}
      hitSlop={{ top: 4, bottom: 4 }}
      style={[
        styles.chip,
        icon ? { flexDirection: 'row' as const, alignItems: 'center' as const, gap: 6 } : null,
        selected && styles.chipOn,
      ]}
    >
      {icon ? (
        <Icon name={icon} size={15} color={selected ? palette.accentOn : palette.accentText} />
      ) : null}
      <Text style={[styles.chipText, selected && styles.chipTextOn]}>{label}</Text>
    </PressableScale>
  );
}

export function TextField(props: TextInputProps) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  return (
    <TextInput
      placeholderTextColor={palette.textMuted}
      selectionColor={palette.accentText}
      cursorColor={palette.accentText}
      {...props}
      style={[styles.input, props.style]}
    />
  );
}

export function SearchField(props: TextInputProps) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  return (
    <View style={styles.searchWrap}>
      <TextField
        autoCapitalize="none"
        autoCorrect={false}
        returnKeyType="search"
        {...props}
        style={[styles.searchInput, props.style]}
      />
      <View style={styles.searchIcon} pointerEvents="none">
        <Icon name="search" size={18} color={palette.textMuted} />
      </View>
    </View>
  );
}

export function Loading() {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  return <ActivityIndicator style={styles.loading} color={palette.accentText} />;
}

/**
 * A quiet stand-in for a section or screen that has no data and could not load it. Not an error:
 * the app retries by itself, so there is nothing to press. `reason` is the agent's message, if any.
 */
export function LoadFailed({
  what,
  reason,
  retrying = true,
}: {
  what: string;
  reason?: string | null;
  /** False when asking again will not help; the card then only gives the reason. */
  retrying?: boolean;
}) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  return (
    <View accessible accessibilityLiveRegion="polite" style={styles.failed}>
      <Icon name="cloud-off" size={24} color={palette.textMuted} />
      <Text style={styles.failedTitle}>{`Couldn't load ${what}`}</Text>
      {retrying ? <Text style={styles.failedLine}>Retrying automatically…</Text> : null}
      {reason ? <Text style={styles.failedReason}>{reason}</Text> : null}
    </View>
  );
}

/** Shown above data that is a refresh behind: the last load failed and a retry is under way. */
export function StaleNote() {
  const styles = useThemedStyles(makeStyles);
  return <Text style={styles.stale}>Showing earlier data · retrying</Text>;
}

// --- Card lists -------------------------------------------------------------------------------

/** A small round status mark: green for money in or done, red for money out or failed. */
export function StatusDot({ color }: { color: string }) {
  const styles = useThemedStyles(makeStyles);
  return <View style={[styles.dot, { backgroundColor: color }]} />;
}

/** A rounded icon tile, the leading element of a list card. */
export function IconTile({
  icon,
  tint,
  soft,
  size = TILE,
}: {
  icon: IconName;
  tint?: string;
  /** Background; defaults to the quiet fill. */
  soft?: string;
  size?: number;
}) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  return (
    <View
      style={[
        styles.iconTile,
        { width: size, height: size, borderRadius: Math.round(size * 0.3) },
        soft ? { backgroundColor: soft } : null,
      ]}
    >
      <Icon name={icon} size={Math.round(size * 0.45)} color={tint ?? palette.accentText} />
    </View>
  );
}

/** Rows rise and fade in one after another, once, when the list first appears. */
export function Stagger({ index, children }: { index: number; children: ReactNode }) {
  // Built once per index: a builder rebuilt in render costs every re-render.
  const entering = useMemo(
    () =>
      FadeInDown.duration(motion.enterMs).delay(
        Math.min(index, motion.staggerMax) * motion.staggerMs,
      ),
    [index],
  );
  return <Animated.View entering={entering}>{children}</Animated.View>;
}

/**
 * A titled list where each row is its own rounded card. `stagger` lets the rows enter one after
 * another the first time they appear: for content the owner opened the screen to see, not for
 * settings they pass every day.
 */
export function ListSection({
  title,
  action,
  footer,
  children,
  stagger,
}: {
  title?: string;
  /** A small link on the right of the title, e.g. "See all". */
  action?: { label: string; onPress: () => void };
  footer?: ReactNode;
  children: ReactNode;
  stagger?: boolean;
}) {
  const styles = useThemedStyles(makeStyles);
  const rows = Children.toArray(children).filter(isValidElement);
  return (
    <View>
      {title ? (
        <View style={styles.sectionHead}>
          <SectionTitle>{title}</SectionTitle>
          {action ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={`${action.label}: ${title}`}
              onPress={action.onPress}
              hitSlop={HIT_SLOP}
            >
              <Text maxFontSizeMultiplier={MAX_CHROME_SCALE} style={styles.sectionAction}>
                {action.label}
              </Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}
      {rows.length > 0 ? (
        <View style={styles.cards}>
          {stagger
            ? rows.map((row, i) => (
                <Stagger key={row.key ?? i} index={i}>
                  {row}
                </Stagger>
              ))
            : rows}
        </View>
      ) : null}
      {typeof footer === 'string' ? <Text style={styles.sectionFooter}>{footer}</Text> : footer}
    </View>
  );
}

export function ListRow({
  title,
  subtitle,
  value,
  dot,
  valueMuted,
  meta,
  icon,
  iconTint,
  leading,
  onPress,
  onLongPress,
  chevron,
  accessory,
  children,
  strong,
  titleLines = 1,
  subtitleLines = 2,
  accessibilityLabel,
  accessibilityHint,
  accessibilityRole,
  accessibilityActions,
  onAccessibilityAction,
  selected,
  destructive,
}: A11y & {
  title: string;
  subtitle?: string | null;
  /** Trailing value text, e.g. an amount or a setting's current choice. */
  value?: string | null;
  /** A status dot beside the value: green/red for money in/out. */
  dot?: string;
  /** A quiet value (a time) instead of a strong one (an amount). */
  valueMuted?: boolean;
  /** Trailing small content, e.g. a badge. */
  meta?: ReactNode;
  icon?: IconName;
  iconTint?: string;
  /** Leading content instead of an icon tile, e.g. an initials avatar. */
  leading?: ReactNode;
  onPress?: () => void;
  onLongPress?: () => void;
  chevron?: boolean;
  accessory?: ReactNode;
  /** Extra content under the title block (badges, inline actions). */
  children?: ReactNode;
  strong?: boolean;
  titleLines?: number;
  subtitleLines?: number;
  selected?: boolean;
  destructive?: boolean;
}) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  const tint = destructive ? palette.danger : (iconTint ?? palette.accentText);
  const top = children ? { alignSelf: 'flex-start' as const } : null;
  const content = (
    <>
      {leading ? <View style={top}>{leading}</View> : null}
      {icon && !leading ? (
        <View style={top}>
          <IconTile icon={icon} tint={tint} soft={destructive ? palette.dangerSoft : undefined} />
        </View>
      ) : null}
      <View style={styles.rowMain}>
        <Text
          numberOfLines={titleLines}
          style={[
            styles.rowTitle,
            strong && styles.rowTitleStrong,
            destructive && { color: palette.danger },
            selected && { color: palette.accentText },
          ]}
        >
          {title}
        </Text>
        {subtitle ? (
          <Text numberOfLines={subtitleLines} style={styles.rowSubtitle}>
            {subtitle}
          </Text>
        ) : null}
        {children}
      </View>
      {value ? (
        <View style={styles.rowTrail}>
          <View style={styles.rowValueLine}>
            <Text numberOfLines={1} style={[styles.rowValue, valueMuted && styles.rowValueMuted]}>
              {value}
            </Text>
            {dot ? <StatusDot color={dot} /> : null}
          </View>
        </View>
      ) : null}
      {meta ? <View style={styles.rowMeta}>{meta}</View> : null}
      {accessory}
      {chevron ? <Icon name="chevron-right" size={18} color={palette.textMuted} /> : null}
    </>
  );
  if (!onPress && !onLongPress) {
    return (
      <View
        style={[styles.row, selected && styles.rowSelected]}
        accessible={!!accessibilityLabel}
        accessibilityLabel={accessibilityLabel}
      >
        {content}
      </View>
    );
  }
  return (
    <PressableScale
      accessibilityRole={accessibilityRole ?? 'button'}
      accessibilityLabel={accessibilityLabel ?? [title, subtitle, value].filter(Boolean).join(', ')}
      accessibilityHint={accessibilityHint}
      accessibilityState={{ selected: !!selected }}
      accessibilityActions={accessibilityActions}
      onAccessibilityAction={onAccessibilityAction}
      onPress={onPress}
      onLongPress={onLongPress}
      scaleTo={motion.pressScaleCard}
      style={[styles.row, selected && styles.rowSelected]}
    >
      {content}
    </PressableScale>
  );
}

export function EmptyRow({ children }: { children: ReactNode }) {
  const styles = useThemedStyles(makeStyles);
  return <Text style={styles.emptyRow}>{children}</Text>;
}

// --- Badges and notices -----------------------------------------------------------------------

export type Tone = 'accent' | 'warn' | 'danger' | 'ok' | 'neutral';

export function toneColors(p: Palette, tone: Tone): { fg: string; bg: string } {
  switch (tone) {
    case 'accent':
      return { fg: p.accentText, bg: p.accentSoft };
    case 'warn':
      return { fg: p.warn, bg: p.warnSoft };
    case 'danger':
      return { fg: p.danger, bg: p.dangerSoft };
    case 'ok':
      return { fg: p.ok, bg: p.okSoft };
    case 'neutral':
      return { fg: p.textMuted, bg: p.muted };
  }
}

/** A short uppercase tag. The label is spoken as written, with `spoken` as an optional expansion. */
export function Badge({
  label,
  tone = 'neutral',
  icon,
  spoken,
}: {
  label: string;
  tone?: Tone;
  icon?: IconName;
  spoken?: string;
}) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  const { fg, bg } = toneColors(palette, tone);
  return (
    <View
      accessible
      accessibilityRole="text"
      accessibilityLabel={spoken ?? label}
      style={[styles.badge, { backgroundColor: bg }]}
    >
      {icon ? <Icon name={icon} size={11} color={fg} /> : null}
      <Text maxFontSizeMultiplier={MAX_CHROME_SCALE} style={[styles.badgeText, { color: fg }]}>
        {label}
      </Text>
    </View>
  );
}

export function Notice({
  tone,
  title,
  children,
  icon,
}: {
  tone: Tone;
  title?: string;
  children?: ReactNode;
  icon?: IconName;
}) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  const { fg, bg } = toneColors(palette, tone);
  const glyph: IconName =
    icon ?? (tone === 'danger' ? 'alert-octagon' : tone === 'warn' ? 'alert-triangle' : 'info');
  return (
    <View
      accessible
      accessibilityRole={tone === 'danger' ? 'alert' : undefined}
      style={[styles.notice, { backgroundColor: bg }]}
    >
      <Icon name={glyph} size={18} color={fg} />
      <View style={styles.noticeMain}>
        {title ? <Text style={[styles.noticeTitle, { color: fg }]}>{title}</Text> : null}
        {children ? (
          <Text style={[styles.noticeBody, { color: title ? palette.text : fg }]}>{children}</Text>
        ) : null}
      </View>
    </View>
  );
}

/**
 * Switch colours for the violet theme. `activeThumbColor` is read by react-native-web only (the
 * screenshot harness); Android uses `thumbColor`.
 */
export function switchColors(p: Palette) {
  return {
    trackColor: { true: p.accentStrong, false: p.border },
    thumbColor: p.accentOn,
    activeThumbColor: p.accentOn,
  };
}

// --- Segmented control ------------------------------------------------------------------------

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  accessibilityLabel,
}: {
  options: readonly { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  accessibilityLabel: string;
}) {
  const styles = useThemedStyles(makeStyles);
  return (
    <View
      accessibilityRole="radiogroup"
      accessibilityLabel={accessibilityLabel}
      style={styles.segmented}
    >
      {options.map((option) => {
        const on = option.value === value;
        return (
          <Pressable
            key={option.value}
            accessibilityRole="radio"
            accessibilityLabel={option.label}
            accessibilityState={{ checked: on }}
            onPress={() => {
              if (on) return;
              haptics.selection();
              onChange(option.value);
            }}
            hitSlop={HIT_SLOP}
            style={{ flex: 1 }}
          >
            <Animated.View style={[styles.segment, on && styles.segmentOn]}>
              <Text
                numberOfLines={1}
                maxFontSizeMultiplier={MAX_CHROME_SCALE}
                style={[styles.segmentText, on && styles.segmentTextOn]}
              >
                {option.label}
              </Text>
            </Animated.View>
          </Pressable>
        );
      })}
    </View>
  );
}
