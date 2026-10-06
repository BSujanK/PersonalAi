import * as Clipboard from 'expo-clipboard';
import { memo, useEffect, useRef, useState } from 'react';
import { Text, View } from 'react-native';

import type { ChatMessage } from '../../lib/chatState';
import {
  MIN_TARGET,
  radius,
  space,
  type,
  useTheme,
  useThemedStyles,
  type Palette,
} from '../../theme';
import { SparkAvatar } from '../brand/Spark';
import { Icon } from '../Icon';
import { ErrorText, PressableScale } from '../ui';
import { ApprovalCard } from './ApprovalCard';
import { Markdown } from './Markdown';
import { ToolActivity } from './ToolActivity';

const COPIED_MS = 1500;

const makeStyles = (p: Palette) => ({
  userRow: { alignItems: 'flex-end' as const, paddingLeft: space.xxl },
  userBubble: {
    backgroundColor: p.accentStrong,
    borderRadius: radius.xl - 2,
    borderBottomRightRadius: radius.sm - 2,
    paddingHorizontal: space.md - 2,
    paddingVertical: space.sm + 2,
  },
  userText: { ...type.body, color: p.accentOn },
  assistantRow: { flexDirection: 'row' as const, gap: space.sm + space.xs },
  assistant: { flex: 1, gap: space.sm + space.xs, paddingTop: 4 },
  thinkingRow: { flexDirection: 'row' as const, alignItems: 'center' as const, minHeight: 28 },
  thinking: { ...type.body, color: p.textMuted },
  note: { ...type.footnote, color: p.textMuted },
  actions: {
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    marginLeft: -space.sm - 2,
  },
  action: {
    minWidth: MIN_TARGET,
    minHeight: MIN_TARGET,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
    borderRadius: MIN_TARGET / 2,
  },
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
    <PressableScale
      accessibilityLabel={label}
      disabled={disabled}
      onPress={onPress}
      style={styles.action}
    >
      <Icon name={icon} size={18} color={palette.textMuted} />
    </PressableScale>
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
    <View style={styles.assistantRow}>
      <SparkAvatar size={30} thinking={streaming} />
      <View style={styles.assistant}>
        <ToolActivity activity={message.tools} />
        {hasText ? <Markdown text={message.text} /> : null}
        {streaming && !hasText && message.tools.length === 0 ? (
          <View style={styles.thinkingRow}>
            <Text accessibilityLiveRegion="polite" style={styles.thinking}>
              Thinking…
            </Text>
          </View>
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
    </View>
  );
}

export const AssistantMessage = memo(AssistantMessageImpl);
