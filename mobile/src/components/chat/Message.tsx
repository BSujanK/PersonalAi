import * as Clipboard from 'expo-clipboard';
import { memo, useEffect, useRef, useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import type { ChatMessage } from '../../lib/chatState';
import { fontFamily, MIN_TARGET, size, useTheme, useThemedStyles, type Palette } from '../../theme';
import { Icon } from '../Icon';
import { ErrorText } from '../ui';
import { ApprovalCard } from './ApprovalCard';
import { Markdown } from './Markdown';
import { ToolActivity } from './ToolActivity';

const COPIED_MS = 1500;

const makeStyles = (p: Palette) => ({
  userRow: { alignItems: 'flex-end' as const, paddingLeft: 48 },
  userBubble: {
    backgroundColor: p.muted,
    borderRadius: 20,
    borderBottomRightRadius: 6,
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  userText: { fontFamily: fontFamily.body, fontSize: size.body, lineHeight: 24, color: p.text },
  assistant: { gap: 10 },
  thinking: { fontFamily: fontFamily.body, fontSize: size.body, color: p.textMuted },
  note: { fontFamily: fontFamily.body, fontSize: size.small, color: p.textMuted },
  actions: { flexDirection: 'row' as const, alignItems: 'center' as const, marginLeft: -10 },
  action: {
    minWidth: MIN_TARGET,
    minHeight: MIN_TARGET,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
    borderRadius: MIN_TARGET / 2,
  },
  actionPressed: { backgroundColor: p.muted },
});

function ActionButton({
  icon,
  label,
  onPress,
  disabled,
}: {
  icon: 'copy' | 'check' | 'refresh-cw';
  label: string;
  onPress: () => void;
  disabled?: boolean;
}) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: !!disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [styles.action, pressed && styles.actionPressed]}
    >
      <Icon name={icon} size={18} color={disabled ? palette.border : palette.textMuted} />
    </Pressable>
  );
}

export function UserMessage({ message }: { message: ChatMessage }) {
  const styles = useThemedStyles(makeStyles);
  return (
    <View style={styles.userRow}>
      <View style={styles.userBubble}>
        <Text selectable style={styles.userText}>
          {message.text}
        </Text>
      </View>
    </View>
  );
}

interface AssistantProps {
  message: ChatMessage;
  /** Retry is offered on the latest answer only, and not while another turn is running. */
  canRetry: boolean;
  onRetry: (id: string) => void;
}

function AssistantMessageImpl({ message, canRetry, onRetry }: AssistantProps) {
  const styles = useThemedStyles(makeStyles);
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);

  const streaming = message.state === 'streaming';
  const hasText = message.text.length > 0;

  async function copy() {
    await Clipboard.setStringAsync(message.text);
    setCopied(true);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), COPIED_MS);
  }

  return (
    <View style={styles.assistant}>
      <ToolActivity activity={message.tools} />
      {hasText ? <Markdown text={message.text} /> : null}
      {streaming && !hasText && message.tools.length === 0 ? (
        <Text accessibilityLiveRegion="polite" style={styles.thinking}>
          Thinking…
        </Text>
      ) : null}
      {message.actionIds.map((id) => (
        <ApprovalCard key={id} actionId={id} />
      ))}
      {message.state === 'stopped' ? (
        <Text style={styles.note}>
          Stopped. The agent may still finish this turn on the laptop.
        </Text>
      ) : null}
      {message.state === 'error' ? (
        <ErrorText message={message.error ?? 'Something went wrong.'} />
      ) : null}
      {!streaming ? (
        <View style={styles.actions}>
          {hasText ? (
            <ActionButton
              icon={copied ? 'check' : 'copy'}
              label={copied ? 'Copied' : 'Copy reply'}
              onPress={() => void copy()}
            />
          ) : null}
          {canRetry ? (
            <ActionButton icon="refresh-cw" label="Retry" onPress={() => onRetry(message.id)} />
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

export const AssistantMessage = memo(AssistantMessageImpl);
