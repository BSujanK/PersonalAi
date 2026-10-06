import { useState } from 'react';
import { Modal, Pressable, Text, View } from 'react-native';

import { errorMessage } from '../../lib/format';
import type { ConversationSummary } from '../../lib/api';
import { fontFamily, MIN_TARGET, type, useTheme, useThemedStyles, type Palette } from '../../theme';
import { Icon, type IconName } from '../Icon';
import { Button, ErrorText, TextField } from '../ui';

const makeStyles = (p: Palette) => ({
  scrim: { flex: 1, backgroundColor: p.overlay, justifyContent: 'flex-end' as const },
  sheet: {
    backgroundColor: p.surface,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    padding: 16,
    paddingBottom: 28,
    gap: 4,
  },
  sheetTitle: {
    ...type.title2,
    color: p.text,
    paddingHorizontal: 8,
    paddingBottom: 8,
  },
  row: {
    minHeight: MIN_TARGET + 4,
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    gap: 14,
    paddingHorizontal: 8,
    borderRadius: 12,
  },
  rowPressed: { backgroundColor: p.muted },
  rowText: { ...type.body, fontFamily: fontFamily.bodyMedium, color: p.text },
  rowDanger: { color: p.danger },
  dialog: { gap: 12 },
  buttons: { flexDirection: 'row' as const, gap: 10 },
  grow: { flex: 1 },
});

function Row({
  icon,
  label,
  onPress,
  danger,
}: {
  icon: IconName;
  label: string;
  onPress: () => void;
  danger?: boolean;
}) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={onPress}
      style={({ pressed }) => [styles.row, pressed && styles.rowPressed]}
    >
      <Icon name={icon} size={20} color={danger ? palette.danger : palette.text} />
      <Text style={[styles.rowText, danger && styles.rowDanger]}>{label}</Text>
    </Pressable>
  );
}

/** Long-press menu for one conversation: rename or delete. Mount with key={target.id}. */
export function ConversationActions({
  target,
  onClose,
  onRename,
  onDelete,
}: {
  target: ConversationSummary | null;
  onClose: () => void;
  onRename: (id: string, title: string) => Promise<void>;
  onDelete: (conversation: ConversationSummary) => void;
}) {
  const styles = useThemedStyles(makeStyles);
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState(target?.title ?? '');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    if (!target || !title.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await onRename(target.id, title.trim());
      onClose();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal visible={target !== null} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable
        style={styles.scrim}
        onPress={onClose}
        accessibilityLabel="Close menu"
        accessibilityRole="button"
      >
        {/* A plain View stops taps on the sheet from reaching the scrim. */}
        <View style={styles.sheet} onStartShouldSetResponder={() => true}>
          {renaming ? (
            <View style={styles.dialog}>
              <Text accessibilityRole="header" style={styles.sheetTitle}>
                Rename chat
              </Text>
              <TextField
                accessibilityLabel="Chat title"
                value={title}
                onChangeText={setTitle}
                autoFocus
                maxLength={200}
                returnKeyType="done"
                onSubmitEditing={() => void save()}
              />
              <ErrorText message={error} />
              <View style={styles.buttons}>
                <View style={styles.grow}>
                  <Button label="Cancel" tone="plain" onPress={onClose} />
                </View>
                <View style={styles.grow}>
                  <Button
                    label={saving ? 'Saving...' : 'Save'}
                    onPress={() => void save()}
                    disabled={saving || !title.trim()}
                  />
                </View>
              </View>
            </View>
          ) : (
            <>
              <Text style={styles.sheetTitle} numberOfLines={1}>
                {target?.title}
              </Text>
              <Row icon="edit-2" label="Rename" onPress={() => setRenaming(true)} />
              <Row
                icon="trash-2"
                label="Delete"
                danger
                onPress={() => target && onDelete(target)}
              />
            </>
          )}
        </View>
      </Pressable>
    </Modal>
  );
}
