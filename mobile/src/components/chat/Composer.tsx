import { useState } from 'react';
import { Pressable, Text, TextInput, View } from 'react-native';

import { fontFamily, MIN_TARGET, size, useTheme, useThemedStyles, type Palette } from '../../theme';
import { Icon } from '../Icon';

const makeStyles = (p: Palette) => ({
  wrap: { paddingHorizontal: 12, paddingTop: 8, paddingBottom: 8, gap: 6 },
  offline: {
    alignSelf: 'center' as const,
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    gap: 6,
  },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: p.danger },
  offlineText: { fontFamily: fontFamily.body, fontSize: size.caption + 1, color: p.textMuted },
  box: {
    flexDirection: 'row' as const,
    alignItems: 'flex-end' as const,
    gap: 8,
    backgroundColor: p.surface,
    borderColor: p.border,
    borderWidth: 1,
    borderRadius: 26,
    paddingLeft: 16,
    paddingRight: 6,
    paddingVertical: 6,
  },
  input: {
    flex: 1,
    maxHeight: 140,
    minHeight: MIN_TARGET - 4,
    paddingTop: 8,
    paddingBottom: 8,
    fontFamily: fontFamily.body,
    fontSize: size.body,
    color: p.text,
  },
  send: {
    width: MIN_TARGET,
    height: MIN_TARGET,
    borderRadius: MIN_TARGET / 2,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
    backgroundColor: p.accent,
  },
  sendOff: { backgroundColor: p.muted },
});

interface Props {
  busy: boolean;
  /** null while the first check is running; false disables sending. */
  online: boolean | null;
  onSend: (text: string) => void;
  onStop: () => void;
}

/** Rounded multi-line input with a send button that turns into stop while a reply streams. */
export function Composer({ busy, online, onSend, onStop }: Props) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  const [draft, setDraft] = useState('');
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
          multiline
          editable={!offline}
          textAlignVertical="center"
        />
        {busy ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Stop generating"
            onPress={onStop}
            style={styles.send}
          >
            <Icon name="square" size={16} color={palette.accentOn} />
          </Pressable>
        ) : (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Send message"
            accessibilityState={{ disabled: !canSend }}
            disabled={!canSend}
            onPress={submit}
            style={[styles.send, !canSend && styles.sendOff]}
          >
            <Icon
              name="arrow-up"
              size={20}
              color={canSend ? palette.accentOn : palette.textMuted}
            />
          </Pressable>
        )}
      </View>
    </View>
  );
}
