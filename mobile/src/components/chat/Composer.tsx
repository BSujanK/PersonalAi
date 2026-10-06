import { useState } from 'react';
import { Text, TextInput, View } from 'react-native';

import {
  MIN_TARGET,
  radius,
  space,
  type,
  useTheme,
  useThemedStyles,
  type Palette,
} from '../../theme';
import { Icon } from '../Icon';
import { PressableScale } from '../ui';

const makeStyles = (p: Palette) => ({
  wrap: {
    paddingHorizontal: space.sm + space.xs,
    paddingTop: space.sm,
    paddingBottom: space.sm,
    gap: space.sm,
  },
  offline: {
    alignSelf: 'center' as const,
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    gap: space.sm,
  },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: p.danger },
  offlineText: { ...type.footnote, color: p.textMuted },
  box: {
    flexDirection: 'row' as const,
    alignItems: 'flex-end' as const,
    gap: space.sm,
    backgroundColor: p.raised,
    borderColor: p.glassBorder,
    borderWidth: 1,
    borderRadius: radius.xxl,
    paddingLeft: space.md,
    paddingRight: space.xs + 2,
    paddingVertical: space.xs + 2,
  },
  input: {
    ...type.body,
    flex: 1,
    maxHeight: 160,
    minHeight: MIN_TARGET - 4,
    paddingTop: space.sm + 2,
    paddingBottom: space.sm + 2,
    color: p.text,
  },
  send: {
    width: 40,
    height: 40,
    margin: 1,
    borderRadius: 20,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
    backgroundColor: p.accentStrong,
  },
  sendOff: { backgroundColor: p.muted },
});

interface Props {
  busy: boolean;
  /** null while the first check is running; false disables sending. */
  online: boolean | null;
  onSend: (text: string) => void;
  onStop: () => void;
  /** Prefilled text, e.g. from "Ask agent about this". Never sent without a tap on Send. */
  initialDraft?: string;
}

/** Rounded multi-line input with a send button that turns into stop while a reply streams. */
export function Composer({ busy, online, onSend, onStop, initialDraft = '' }: Props) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  const [draft, setDraft] = useState(initialDraft);
  const offline = online === false;
  const canSend = !offline && draft.trim().length > 0;

  function submit() {
    if (!canSend || busy) return;
    onSend(draft);
    setDraft('');
  }

  return (
    <View style={styles.wrap}>
      {offline ? (
        <View style={styles.offline} accessibilityRole="alert">
          <View style={styles.dot} />
          <Text style={styles.offlineText}>Agent offline. Check the laptop and Tailscale.</Text>
        </View>
      ) : null}
      <View style={styles.box}>
        <TextInput
          accessibilityLabel="Message"
          style={styles.input}
          value={draft}
          onChangeText={setDraft}
          placeholder={offline ? 'Agent offline' : 'Message PersonalAi'}
          placeholderTextColor={palette.textMuted}
          selectionColor={palette.accentText}
          cursorColor={palette.accentText}
          multiline
          autoFocus={initialDraft.length > 0}
          editable={!offline}
          textAlignVertical="center"
        />
        {busy ? (
          <PressableScale
            accessibilityLabel="Stop generating"
            onPress={onStop}
            hitSlop={4}
            style={styles.send}
          >
            <Icon name="square" size={14} color={palette.accentOn} />
          </PressableScale>
        ) : (
          <PressableScale
            accessibilityLabel="Send message"
            disabled={!canSend}
            onPress={submit}
            hitSlop={4}
            style={[styles.send, !canSend && styles.sendOff]}
          >
            <Icon
              name="arrow-up"
              size={20}
              color={canSend ? palette.accentOn : palette.textMuted}
            />
          </PressableScale>
        )}
      </View>
    </View>
  );
}
