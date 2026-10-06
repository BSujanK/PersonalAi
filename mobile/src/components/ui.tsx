// The app's component kit. Restraint first: one accent, grouped inset lists, an 8-pt grid, 44-pt
// targets, and press feedback that is felt more than seen (scale 0.97 over 120 ms, on press-in).
import { Children, Fragment, isValidElement, useState, type ReactNode } from 'react';
import {
  ActivityIndicator,
  Pressable,
  Text,
  TextInput,
  View,
  type AccessibilityRole,
  type Insets,
  type StyleProp,
  type TextInputProps,
  type ViewStyle,
} from 'react-native';
import Animated, { useReducedMotion } from 'react-native-reanimated';

import { haptics } from '../lib/haptics';
import {
  fontFamily,
  MAX_CHROME_SCALE,
  MIN_TARGET,
  easeOut,
  motion,
  radius,
  ROW_INSET,
  space,
  type,
  useTheme,
  useThemedStyles,
} from '../theme';
import type { Palette } from '../theme';
import { Icon, type IconName } from './Icon';

/** Readable column: full width on a phone, capped and centred on wider screens. */
export const COLUMN_MAX = 720;

const HIT_SLOP: Insets = { top: 8, bottom: 8, left: 8, right: 8 };

const makeStyles = (p: Palette) => ({
  press: {
    transform: [{ scale: 1 }],
    opacity: 1,
    transitionProperty: ['transform', 'opacity'],
    transitionDuration: motion.pressMs,
    transitionTimingFunction: easeOut,
  },
  pressedScale: { transform: [{ scale: motion.pressScale }] },
  pressedDim: { opacity: 0.6 },
  iconButton: {
    width: MIN_TARGET,
    height: MIN_TARGET,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
    borderRadius: MIN_TARGET / 2,
  },
  title: { ...type.title1, color: p.text },
  section: {
    ...type.footnote,
    fontFamily: fontFamily.bodySemiBold,
    letterSpacing: 0.4,
    textTransform: 'uppercase' as const,
    color: p.textMuted,
    marginTop: space.sm,
  },
  card: {
    backgroundColor: p.surface,
    borderRadius: radius.lg,
    padding: space.md,
    gap: space.sm,
  },
  body: { ...type.body, color: p.text },
  caption: { ...type.footnote, color: p.textMuted },
  muted: { color: p.textMuted },
  error: { ...type.subhead, color: p.danger },
  button: {
    borderRadius: radius.md,
    minHeight: 50,
    paddingVertical: space.sm + space.xs,
    paddingHorizontal: space.md,
    flexDirection: 'row' as const,
    gap: space.sm,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
  },
  buttonCompact: { minHeight: MIN_TARGET, paddingVertical: space.sm },
  buttonText: { ...type.headline },
  chip: {
    minHeight: 36,
    justifyContent: 'center' as const,
    paddingHorizontal: space.md,
    borderRadius: radius.pill,
    backgroundColor: p.muted,
  },
  chipOn: { backgroundColor: p.accent },
  chipText: { ...type.subhead, fontFamily: fontFamily.bodyMedium, color: p.text },
  chipTextOn: { color: p.accentOn },
  input: {
    ...type.body,
    minHeight: MIN_TARGET + 4,
    borderRadius: radius.md,
    paddingHorizontal: space.md - space.xs,
    paddingVertical: space.sm + space.xs,
    backgroundColor: p.muted,
    color: p.text,
  },
  searchWrap: { justifyContent: 'center' as const },
  searchInput: { paddingLeft: space.xl + space.sm },
  searchIcon: { position: 'absolute' as const, left: space.md - space.xs },
  loading: { marginVertical: space.lg },
  // Grouped inset list
  groupHeader: {
    ...type.footnote,
    fontFamily: fontFamily.bodySemiBold,
    letterSpacing: 0.4,
    textTransform: 'uppercase' as const,
    color: p.textMuted,
    paddingHorizontal: ROW_INSET,
    paddingBottom: space.sm,
  },
  groupFooter: {
    ...type.footnote,
    color: p.textMuted,
    paddingHorizontal: ROW_INSET,
    paddingTop: space.sm,
  },
  group: { backgroundColor: p.surface, borderRadius: radius.md, overflow: 'hidden' as const },
  separator: { height: 1, backgroundColor: p.separator, marginLeft: ROW_INSET },
  separatorIcon: { marginLeft: ROW_INSET + 30 + space.md - space.xs },
  row: {
    minHeight: MIN_TARGET + 4,
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    gap: space.md - space.xs,
    paddingHorizontal: ROW_INSET,
    paddingVertical: space.sm + space.xs,
    backgroundColor: p.surface,
  },
  rowPressed: { backgroundColor: p.muted },
  rowMain: { flex: 1, gap: 2 },
  rowTitle: { ...type.body, color: p.text },
  rowTitleStrong: { fontFamily: fontFamily.bodySemiBold },
  rowSubtitle: { ...type.subhead, color: p.textMuted },
  rowValue: { ...type.body, color: p.textMuted, flexShrink: 0, maxWidth: '50%' as const },
  rowMeta: { alignItems: 'flex-end' as const, gap: space.xs, flexShrink: 0 },
  iconTile: {
    width: 30,
    height: 30,
    borderRadius: radius.sm,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
  },
  emptyRow: { ...type.body, color: p.textMuted, padding: ROW_INSET },
  // Badges
  badge: {
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    gap: 3,
    alignSelf: 'flex-start' as const,
    paddingHorizontal: space.sm,
    paddingVertical: 2,
    borderRadius: radius.sm - 2,
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
    borderRadius: radius.md,
  },
  noticeMain: { flex: 1, gap: 2 },
  noticeTitle: { ...type.subhead, fontFamily: fontFamily.bodySemiBold },
  noticeBody: { ...type.subhead },
  // Segmented control
  segmented: {
    flexDirection: 'row' as const,
    backgroundColor: p.muted,
    borderRadius: radius.md - 2,
    padding: 2,
  },
  segment: {
    flex: 1,
    minHeight: MIN_TARGET - 8,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
    borderRadius: radius.sm,
    paddingHorizontal: space.sm,
    backgroundColor: 'transparent',
    transitionProperty: 'backgroundColor',
    transitionDuration: motion.stateMs,
    transitionTimingFunction: easeOut,
  },
  segmentOn: { backgroundColor: p.elevated },
  segmentText: { ...type.subhead, fontFamily: fontFamily.bodyMedium, color: p.textMuted },
  segmentTextOn: { fontFamily: fontFamily.bodySemiBold, color: p.text },
});

type A11y = {
  accessibilityLabel?: string;
  accessibilityHint?: string;
  accessibilityRole?: AccessibilityRole;
  accessibilityState?: { disabled?: boolean; selected?: boolean; expanded?: boolean };
};

/**
 * The one pressable: feedback on press-in, commit on press-out. Scale 0.97 in 120 ms runs as a
 * Reanimated CSS transition on the UI thread; with Reduce Motion on, it dims instead of scaling.
 */
export function PressableScale({
  children,
  onPress,
  onLongPress,
  disabled,
  style,
  hitSlop,
  dim,
  testID,
  ...a11y
}: A11y & {
  children: ReactNode;
  onPress?: () => void;
  onLongPress?: () => void;
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
  hitSlop?: Insets | number;
  /** Dim instead of scaling, for full-width rows where a scale would read as a jump. */
  dim?: boolean;
  testID?: string;
}) {
  const styles = useThemedStyles(makeStyles);
  const reduced = useReducedMotion();
  const [pressed, setPressed] = useState(false);
  const scale = !dim && !reduced;
  return (
    <Pressable
      accessibilityRole={a11y.accessibilityRole ?? 'button'}
      accessibilityLabel={a11y.accessibilityLabel}
      accessibilityHint={a11y.accessibilityHint}
      accessibilityState={{ ...a11y.accessibilityState, disabled: !!disabled }}
      onPress={onPress}
      onLongPress={onLongPress}
      delayLongPress={onLongPress ? 350 : undefined}
      onPressIn={() => setPressed(true)}
      onPressOut={() => setPressed(false)}
      disabled={disabled}
      hitSlop={hitSlop}
      pressRetentionOffset={16}
      testID={testID}
    >
      <Animated.View
        style={[
          styles.press,
          style,
          pressed && (scale ? styles.pressedScale : styles.pressedDim),
          disabled && { opacity: 0.4 },
        ]}
      >
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
}: {
  icon: IconName;
  label: string;
  onPress: () => void;
  disabled?: boolean;
  color?: string;
  size?: number;
}) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  return (
    <PressableScale
      accessibilityLabel={label}
      onPress={onPress}
      disabled={disabled}
      hitSlop={4}
      style={styles.iconButton}
    >
      <Icon name={icon} size={size} color={color ?? palette.accentText} />
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
    <Text accessibilityRole="header" style={styles.section}>
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

function buttonColors(p: Palette, tone: ButtonTone): { bg: string; fg: string } {
  switch (tone) {
    case 'primary':
      return { bg: p.accent, fg: p.accentOn };
    case 'tinted':
      return { bg: p.accentSoft, fg: p.accentText };
    case 'plain':
      return { bg: p.muted, fg: p.text };
    case 'danger':
      return { bg: p.danger, fg: p.dangerOn };
    case 'dangerTinted':
      return { bg: p.dangerSoft, fg: p.danger };
  }
}

export function Button({
  label,
  onPress,
  disabled,
  tone = 'primary',
  icon,
  compact,
  accessibilityLabel,
  accessibilityHint,
}: {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  tone?: ButtonTone;
  icon?: IconName;
  compact?: boolean;
  accessibilityLabel?: string;
  accessibilityHint?: string;
}) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  const { bg, fg } = buttonColors(palette, tone);
  return (
    <PressableScale
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityHint={accessibilityHint}
      onPress={onPress}
      disabled={disabled}
      style={[styles.button, compact && styles.buttonCompact, { backgroundColor: bg }]}
    >
      {icon ? <Icon name={icon} size={18} color={fg} /> : null}
      <Text style={[styles.buttonText, { color: fg }]}>{label}</Text>
    </PressableScale>
  );
}

/** A tappable pill: filter, suggestion or choice. `selected` marks the active choice. */
export function Chip({
  label,
  onPress,
  selected,
  accessibilityLabel,
}: {
  label: string;
  onPress: () => void;
  selected?: boolean;
  accessibilityLabel?: string;
}) {
  const styles = useThemedStyles(makeStyles);
  return (
    <PressableScale
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityState={{ selected: !!selected }}
      onPress={onPress}
      hitSlop={{ top: 4, bottom: 4 }}
      style={[styles.chip, selected && styles.chipOn]}
    >
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

// --- Grouped inset list -----------------------------------------------------------------------

/**
 * A titled group of rows on one rounded surface, with inset hairlines between rows. Rows that
 * have an icon get separators that start after the icon, as in the system settings.
 */
export function ListSection({
  title,
  footer,
  children,
  inset = 'text',
}: {
  title?: string;
  footer?: ReactNode;
  children: ReactNode;
  /** Where row hairlines start: after the text inset, after an icon tile, or at an offset. */
  inset?: 'text' | 'icon' | number;
}) {
  const styles = useThemedStyles(makeStyles);
  const rows = Children.toArray(children).filter(isValidElement);
  return (
    <View>
      {title ? (
        <Text
          accessibilityRole="header"
          maxFontSizeMultiplier={MAX_CHROME_SCALE}
          style={styles.groupHeader}
        >
          {title}
        </Text>
      ) : null}
      {rows.length > 0 ? (
        <View style={styles.group}>
          {rows.map((row, i) => (
            <Fragment key={row.key ?? i}>
              {i > 0 ? (
                <View
                  style={[
                    styles.separator,
                    inset === 'icon' && styles.separatorIcon,
                    typeof inset === 'number' && { marginLeft: inset },
                  ]}
                />
              ) : null}
              {row}
            </Fragment>
          ))}
        </View>
      ) : null}
      {typeof footer === 'string' ? <Text style={styles.groupFooter}>{footer}</Text> : footer}
    </View>
  );
}

export function ListRow({
  title,
  subtitle,
  value,
  meta,
  icon,
  iconTint,
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
  selected,
  destructive,
}: {
  title: string;
  subtitle?: string | null;
  /** Trailing value text, e.g. an amount or a setting's current choice. */
  value?: string | null;
  /** Trailing small content stacked above the chevron area, e.g. a time and badges. */
  meta?: ReactNode;
  icon?: IconName;
  iconTint?: string;
  onPress?: () => void;
  onLongPress?: () => void;
  chevron?: boolean;
  accessory?: ReactNode;
  /** Extra content under the title block (badges, inline actions). */
  children?: ReactNode;
  strong?: boolean;
  titleLines?: number;
  subtitleLines?: number;
  accessibilityLabel?: string;
  accessibilityHint?: string;
  accessibilityRole?: AccessibilityRole;
  selected?: boolean;
  destructive?: boolean;
}) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  const tint = iconTint ?? palette.accentText;
  const content = (
    <>
      {icon ? (
        <View
          style={[
            styles.iconTile,
            { backgroundColor: palette.muted },
            children ? { alignSelf: 'flex-start' as const } : null,
          ]}
        >
          <Icon name={icon} size={17} color={destructive ? palette.danger : tint} />
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
        <Text numberOfLines={1} style={styles.rowValue}>
          {value}
        </Text>
      ) : null}
      {meta ? <View style={styles.rowMeta}>{meta}</View> : null}
      {accessory}
      {chevron ? <Icon name="chevron-right" size={18} color={palette.textMuted} /> : null}
    </>
  );
  if (!onPress && !onLongPress) {
    return (
      <View
        style={styles.row}
        accessible={!!accessibilityLabel}
        accessibilityLabel={accessibilityLabel}
      >
        {content}
      </View>
    );
  }
  return (
    <Pressable
      accessibilityRole={accessibilityRole ?? 'button'}
      accessibilityLabel={accessibilityLabel ?? [title, subtitle, value].filter(Boolean).join(', ')}
      accessibilityHint={accessibilityHint}
      accessibilityState={{ selected: !!selected }}
      onPress={onPress}
      onLongPress={onLongPress}
      delayLongPress={350}
      pressRetentionOffset={16}
      style={({ pressed }) => [styles.row, pressed && styles.rowPressed]}
    >
      {content}
    </Pressable>
  );
}

export function EmptyRow({ children }: { children: ReactNode }) {
  const styles = useThemedStyles(makeStyles);
  return <Text style={styles.emptyRow}>{children}</Text>;
}

// --- Badges and notices -----------------------------------------------------------------------

export type Tone = 'accent' | 'warn' | 'danger' | 'neutral';

export function toneColors(p: Palette, tone: Tone): { fg: string; bg: string } {
  switch (tone) {
    case 'accent':
      return { fg: p.accentText, bg: p.accentSoft };
    case 'warn':
      return { fg: p.warn, bg: p.warnSoft };
    case 'danger':
      return { fg: p.danger, bg: p.dangerSoft };
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
