import type { ReactNode } from 'react';
import {
  ActivityIndicator,
  Pressable,
  Text,
  TextInput,
  View,
  type StyleProp,
  type TextInputProps,
  type ViewStyle,
} from 'react-native';

import { fontFamily, MIN_TARGET, size, useTheme, useThemedStyles } from '../theme';
import type { Palette } from '../theme';
import { Icon, type IconName } from './Icon';

/** Readable column: full width on a phone, capped and centred on wider screens. */
export const COLUMN_MAX = 720;

const makeStyles = (p: Palette) => ({
  iconButton: {
    minWidth: MIN_TARGET,
    minHeight: MIN_TARGET,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
    borderRadius: MIN_TARGET / 2,
  },
  iconButtonPressed: { backgroundColor: p.muted },
  title: { fontFamily: fontFamily.display, fontSize: size.title, color: p.text },
  section: {
    fontFamily: fontFamily.bodySemiBold,
    fontSize: size.small,
    letterSpacing: 0.4,
    textTransform: 'uppercase' as const,
    color: p.textMuted,
    marginTop: 12,
  },
  card: {
    backgroundColor: p.surface,
    borderColor: p.border,
    borderWidth: 1,
    borderRadius: 14,
    padding: 14,
    gap: 6,
  },
  body: { fontFamily: fontFamily.body, fontSize: size.body, color: p.text, lineHeight: 23 },
  caption: { fontFamily: fontFamily.body, fontSize: size.small, color: p.textMuted },
  muted: { color: p.textMuted },
  error: { fontFamily: fontFamily.body, color: p.danger, fontSize: size.small + 1 },
  button: {
    backgroundColor: p.accent,
    borderRadius: 12,
    minHeight: MIN_TARGET,
    paddingVertical: 10,
    paddingHorizontal: 16,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
  },
  buttonDanger: { backgroundColor: p.danger },
  buttonPlain: { backgroundColor: 'transparent', borderColor: p.border, borderWidth: 1 },
  buttonDim: { opacity: 0.55 },
  buttonText: { fontFamily: fontFamily.bodySemiBold, color: p.accentOn, fontSize: size.body - 1 },
  buttonTextDanger: { color: p.dangerOn },
  buttonTextPlain: { color: p.text },
  chip: {
    minHeight: MIN_TARGET,
    justifyContent: 'center' as const,
    paddingHorizontal: 14,
    borderRadius: 22,
    borderWidth: 1,
    borderColor: p.border,
    backgroundColor: p.surface,
  },
  chipOn: { backgroundColor: p.accentSoft, borderColor: p.accent },
  chipText: { fontFamily: fontFamily.body, fontSize: size.small + 1, color: p.text },
  input: {
    minHeight: MIN_TARGET,
    borderWidth: 1,
    borderColor: p.border,
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 10,
    backgroundColor: p.surface,
    color: p.text,
    fontFamily: fontFamily.body,
    fontSize: size.body,
  },
  loading: { marginVertical: 24 },
});

export function IconButton({
  icon,
  label,
  onPress,
  disabled,
  color,
}: {
  icon: IconName;
  label: string;
  onPress: () => void;
  disabled?: boolean;
  color?: string;
}) {
  const styles = useThemedStyles(makeStyles);
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: !!disabled }}
      onPress={onPress}
      disabled={disabled}
      hitSlop={4}
      style={({ pressed }) => [styles.iconButton, pressed && styles.iconButtonPressed]}
    >
      <Icon name={icon} color={color} />
    </Pressable>
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

export function Button({
  label,
  onPress,
  disabled,
  tone = 'primary',
  accessibilityLabel,
}: {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  tone?: 'primary' | 'danger' | 'plain';
  accessibilityLabel?: string;
}) {
  const styles = useThemedStyles(makeStyles);
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      accessibilityState={{ disabled: !!disabled }}
      onPress={onPress}
      disabled={disabled}
      style={({ pressed }) => [
        styles.button,
        tone === 'danger' && styles.buttonDanger,
        tone === 'plain' && styles.buttonPlain,
        (disabled || pressed) && styles.buttonDim,
      ]}
    >
      <Text
        style={[
          styles.buttonText,
          tone === 'danger' && styles.buttonTextDanger,
          tone === 'plain' && styles.buttonTextPlain,
        ]}
      >
        {label}
      </Text>
    </Pressable>
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
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityState={{ selected: !!selected }}
      onPress={onPress}
      style={({ pressed }) => [styles.chip, selected && styles.chipOn, pressed && styles.buttonDim]}
    >
      <Text style={styles.chipText}>{label}</Text>
    </Pressable>
  );
}

export function TextField(props: TextInputProps) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  return (
    <TextInput
      placeholderTextColor={palette.textMuted}
      {...props}
      style={[styles.input, props.style]}
    />
  );
}

export function Loading() {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  return <ActivityIndicator style={styles.loading} color={palette.accent} />;
}
