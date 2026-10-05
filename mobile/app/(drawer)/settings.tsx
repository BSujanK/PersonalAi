import { useCallback, useEffect, useState } from 'react';
import Constants from 'expo-constants';
import { StyleSheet, Switch, Text, View } from 'react-native';

import {
  Body,
  Button,
  Caption,
  Card,
  Chip,
  ErrorText,
  SectionTitle,
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
import { fontFamily, size, useTheme, type ThemePreference } from '../../src/theme';

const IMPORT_DAYS = 30;
const SENDER_ID = /^[A-Z0-9]{3,16}$/;
const THEMES: { value: ThemePreference; label: string }[] = [
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

  return (
    <Screen title="Settings" menu>
      <ErrorText message={error} />
      {status ? <Body muted>{status}</Body> : null}

      <SectionTitle>Appearance</SectionTitle>
      <Card>
        <Body>Theme</Body>
        <View style={styles.chips}>
          {THEMES.map((t) => (
            <Chip
              key={t.value}
              label={t.label}
              selected={preference === t.value}
              onPress={() => setPreference(t.value)}
            />
          ))}
        </View>
        <Caption>System follows the light or dark setting of your phone.</Caption>
      </Card>

      <SectionTitle>Server and pairing</SectionTitle>
      <Card>
        <Body>{pairing?.serverUrl}</Body>
        <Text
          accessibilityRole="text"
          style={{
            fontFamily: fontFamily.bodyMedium,
            fontSize: size.body,
            color: online ? palette.ok : online === null ? palette.textMuted : palette.danger,
          }}
        >
          {online === null ? 'Checking...' : online ? 'Agent online' : 'Agent offline'}
        </Text>
        <Caption>
          Paired device {pairing?.deviceId.slice(0, 8)}. Reached over Tailscale only; approvals need
          your fingerprint or face.
        </Caption>
        <Button label="Unpair this phone" tone="danger" onPress={() => void unpair()} />
      </Card>

      <SectionTitle>SMS senders</SectionTitle>
      <Body muted>
        Only messages from the senders below (and any starting with BOB) are read and sent to your
        laptop.
      </Body>
      <Card>
        <Body>
          {queued} message{queued === 1 ? '' : 's'} waiting to send
        </Body>
        <Button
          label={`Import bank SMS from last ${IMPORT_DAYS} days`}
          onPress={() => void importSms()}
        />
        <Button label="Send queued messages now" tone="plain" onPress={() => void sendQueue()} />
      </Card>
      <Card>
        <Body muted>
          Default senders: {defaults.length > 0 ? defaults.join(', ') : 'none loaded yet'}
        </Body>
        <View style={styles.chips}>
          {custom.map((id) => (
            <Chip
              key={id}
              label={`${id} ✕`}
              accessibilityLabel={`Remove sender ${id}`}
              onPress={() => void removeSender(id)}
            />
          ))}
        </View>
        <TextField
          accessibilityLabel="New sender ID"
          value={newSender}
          onChangeText={setNewSender}
          placeholder="Add a sender ID, e.g. AD-MYBANK"
          autoCapitalize="characters"
          autoCorrect={false}
        />
        <Button
          label="Add sender"
          tone="plain"
          onPress={() => void addSender()}
          disabled={!newSender.trim()}
        />
      </Card>

      <SectionTitle>Notifications</SectionTitle>
      <Card>
        <View style={styles.row}>
          <Body>Push notifications</Body>
          <Switch
            accessibilityLabel="Push notifications"
            value={push}
            onValueChange={(v) => void togglePush(v)}
            disabled={!pushAvailable()}
            trackColor={{ true: palette.accent, false: palette.border }}
          />
        </View>
        {pushAvailable() ? null : (
          <Body muted>Not set up in this build. The app polls every 30 seconds.</Body>
        )}
      </Card>

      <SectionTitle>About</SectionTitle>
      <Card>
        <Body>PersonalAi {Constants.expoConfig?.version ?? ''}</Body>
        <Caption>
          A private assistant that runs on your laptop. Nothing leaves it without your approval, and
          the language model only ever sees redacted text.
        </Caption>
      </Card>
    </Screen>
  );
}

const styles = StyleSheet.create({
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    minHeight: 44,
  },
});
