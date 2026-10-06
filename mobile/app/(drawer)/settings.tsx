import { useCallback, useEffect, useState } from 'react';
import Constants from 'expo-constants';
import { StyleSheet, Switch, Text, View } from 'react-native';

import {
  Button,
  ErrorText,
  IconButton,
  ListRow,
  ListSection,
  Notice,
  SegmentedControl,
  TextField,
} from '../../src/components/ui';
import { Screen } from '../../src/components/Screen';
import { health } from '../../src/lib/api';
import {
  flushSmsQueue,
  getCustomSenders,
  getDefaultSenders,
  hasSmsPermission,
  importRecent,
  refreshDefaultSenders,
  requestSmsPermission,
  saveCustomSenders,
  smsQueueSize,
} from '../../src/lib/bankSms';
import { errorMessage } from '../../src/lib/format';
import { usePairing } from '../../src/lib/PairingContext';
import { disablePush, enablePush, isPushEnabled, pushAvailable } from '../../src/lib/push';
import { clearPairing } from '../../src/lib/secureKeys';
import { normaliseSender } from '../../src/lib/smsSync';
import { usePolling } from '../../src/lib/usePolling';
import { fontFamily, space, type, useTheme, type ThemePreference } from '../../src/theme';

const IMPORT_DAYS = 30;
const SENDER_ID = /^[A-Z0-9]{3,16}$/;
const THEMES: readonly { value: ThemePreference; label: string }[] = [
  { value: 'system', label: 'System' },
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
];

export default function Settings() {
  const { pairing, reload } = usePairing();
  const { palette, preference, setPreference } = useTheme();
  const [online, setOnline] = useState<boolean | null>(null);
  const [defaults, setDefaults] = useState<string[]>([]);
  const [custom, setCustom] = useState<string[]>([]);
  const [newSender, setNewSender] = useState('');
  const [queued, setQueued] = useState(0);
  const [push, setPush] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    void health().then(
      () => setOnline(true),
      () => setOnline(false),
    );
    setQueued(await smsQueueSize().catch(() => 0));
  }, []);

  usePolling(load);

  useEffect(() => {
    void (async () => {
      setDefaults(await getDefaultSenders());
      setCustom(await getCustomSenders());
      setPush(await isPushEnabled());
      setDefaults(await refreshDefaultSenders());
    })();
  }, []);

  async function run(task: () => Promise<string | void>) {
    setError(null);
    setStatus(null);
    try {
      const message = await task();
      if (message) setStatus(message);
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  async function ensureSmsPermission(): Promise<void> {
    if (!(await hasSmsPermission()) && !(await requestSmsPermission())) {
      throw new Error(
        'SMS permission is needed to read bank messages. Grant it in Android settings.',
      );
    }
  }

  const importSms = () =>
    run(async () => {
      await ensureSmsPermission();
      const added = await importRecent(IMPORT_DAYS);
      return `Queued ${added} bank message${added === 1 ? '' : 's'} from the last ${IMPORT_DAYS} days.`;
    });

  const sendQueue = () =>
    run(async () => {
      const { sent, dropped, stoppedBy } = await flushSmsQueue();
      if (stoppedBy === 'offline') return 'Agent offline. Messages stay queued.';
      if (stoppedBy === 'rejected')
        return 'The agent could not take them now. Messages stay queued.';
      const skipped = dropped
        ? ` ${dropped} invalid message${dropped === 1 ? '' : 's'} skipped.`
        : '';
      return `Sent ${sent} message${sent === 1 ? '' : 's'}.${skipped}`;
    });

  const addSender = () =>
    run(async () => {
      const id = normaliseSender(newSender);
      if (!SENDER_ID.test(id))
        throw new Error('Sender IDs are 3-16 letters or digits, like BOBTXN.');
      if (!custom.includes(id) && !defaults.includes(id)) {
        const next = [...custom, id];
        await saveCustomSenders(next);
        setCustom(next);
      }
      setNewSender('');
    });

  const removeSender = (id: string) =>
    run(async () => {
      const next = custom.filter((s) => s !== id);
      await saveCustomSenders(next);
      setCustom(next);
    });

  const togglePush = (value: boolean) =>
    run(async () => {
      if (!value) {
        await disablePush();
        setPush(false);
        return;
      }
      const outcome = await enablePush();
      setPush(outcome === 'enabled');
      if (outcome === 'unavailable')
        return 'Push is not set up in this build. The app polls every 30 seconds instead.';
      if (outcome === 'denied') return 'Notification permission was denied.';
    });

  const unpair = () =>
    run(async () => {
      await clearPairing();
      await reload();
    });

  const statusText = online === null ? 'Checking…' : online ? 'Online' : 'Offline';
  const statusColor = online ? palette.ok : online === null ? palette.textMuted : palette.danger;

  return (
    <Screen title="Settings" menu>
      <ErrorText message={error} />
      {status ? <Notice tone="accent">{status}</Notice> : null}

      <ListSection
        title="Appearance"
        footer="System follows the light or dark setting of your phone."
      >
        <View style={styles.padded}>
          <SegmentedControl
            accessibilityLabel="Theme"
            options={THEMES}
            value={preference}
            onChange={setPreference}
          />
        </View>
      </ListSection>

      <ListSection
        title="Agent"
        inset="icon"
        footer={`Paired device ${pairing?.deviceId.slice(0, 8) ?? ''}. Reached over Tailscale only; approvals need your fingerprint or face.`}
      >
        <ListRow
          icon="activity"
          iconTint={statusColor}
          title="Status"
          accessory={
            <View style={styles.status}>
              <View style={[styles.dot, { backgroundColor: statusColor }]} />
              <Text style={[styles.statusText, { color: statusColor }]}>{statusText}</Text>
            </View>
          }
          accessibilityLabel={`Agent ${statusText}`}
        />
        <ListRow icon="server" title="Server" subtitle={pairing?.serverUrl ?? ''} />
        <ListRow
          icon="link-2"
          title="Unpair this phone"
          destructive
          onPress={() => void unpair()}
          accessibilityHint="Removes the pairing keys from this phone"
        />
      </ListSection>

      <ListSection
        title="Bank SMS"
        inset="icon"
        footer="Only messages from the senders below (and any starting with BOB) are read and sent to your laptop."
      >
        <ListRow
          icon="inbox"
          title="Waiting to send"
          value={`${queued} message${queued === 1 ? '' : 's'}`}
        />
        <ListRow
          icon="download"
          title={`Import last ${IMPORT_DAYS} days`}
          onPress={() => void importSms()}
          chevron
        />
        <ListRow icon="upload" title="Send queued now" onPress={() => void sendQueue()} chevron />
      </ListSection>

      <ListSection
        title="Senders"
        footer={`Built in: ${defaults.length > 0 ? defaults.join(', ') : 'none loaded yet'}`}
      >
        {custom.map((id) => (
          <ListRow
            key={id}
            title={id}
            accessory={
              <IconButton
                icon="minus-circle"
                label={`Remove sender ${id}`}
                color={palette.danger}
                onPress={() => void removeSender(id)}
              />
            }
          />
        ))}
        <View style={[styles.padded, styles.addRow]}>
          <View style={{ flex: 1 }}>
            <TextField
              accessibilityLabel="New sender ID"
              value={newSender}
              onChangeText={setNewSender}
              placeholder="Add a sender, e.g. AD-MYBANK"
              autoCapitalize="characters"
              autoCorrect={false}
              onSubmitEditing={() => void addSender()}
            />
          </View>
          <Button
            label="Add"
            tone="tinted"
            compact
            accessibilityLabel="Add sender"
            onPress={() => void addSender()}
            disabled={!newSender.trim()}
          />
        </View>
      </ListSection>

      <ListSection
        title="Notifications"
        inset="icon"
        footer={
          pushAvailable()
            ? 'Notifications never contain mail, SMS or amounts, only a count.'
            : 'Not set up in this build. The app polls every 30 seconds.'
        }
      >
        <ListRow
          icon="bell"
          title="Push notifications"
          accessory={
            <Switch
              accessibilityLabel="Push notifications"
              value={push}
              onValueChange={(v) => void togglePush(v)}
              disabled={!pushAvailable()}
              trackColor={{ true: palette.accent, false: palette.border }}
              thumbColor={palette.surface}
            />
          }
        />
      </ListSection>

      <ListSection
        title="About"
        footer="A private assistant that runs on your laptop. Nothing leaves it without your approval, and the language model only ever sees redacted text."
      >
        <ListRow title="PersonalAi" value={Constants.expoConfig?.version ?? ''} />
      </ListSection>
    </Screen>
  );
}

const styles = StyleSheet.create({
  padded: { padding: space.md - space.xs },
  addRow: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  status: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  dot: { width: 8, height: 8, borderRadius: 4 },
  statusText: { ...type.callout, fontFamily: fontFamily.bodyMedium },
});
