import { useRouter } from 'expo-router';
import { Text, View } from 'react-native';

import { Spark } from '../src/components/brand/Spark';
import { Screen } from '../src/components/Screen';
import { Card, ListRow, ListSection, StatusDot } from '../src/components/ui';
import { useAgentStatus } from '../src/lib/AgentStatus';
import { usePairing } from '../src/lib/PairingContext';
import { space, type, useTheme, useThemedStyles, type Palette } from '../src/theme';

const makeStyles = (p: Palette) => ({
  profile: { flexDirection: 'row' as const, alignItems: 'center' as const, gap: space.md },
  profileMain: { flex: 1, gap: 2 },
  name: { ...type.title3, color: p.text },
  line: { ...type.footnote, color: p.textMuted },
  statusLine: { flexDirection: 'row' as const, alignItems: 'center' as const, gap: space.sm },
  footer: {
    ...type.footnote,
    color: p.textMuted,
    textAlign: 'center' as const,
    paddingHorizontal: space.md,
  },
});

/**
 * More, opened from the spark in the Chat header: who the agent is, whether it is reachable, and
 * every screen that is not a tab.
 */
export default function More() {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  const router = useRouter();
  const { pairing } = usePairing();
  const { online } = useAgentStatus();

  const statusText = online === null ? 'Checking…' : online ? 'Agent online' : 'Agent offline';
  const statusColor = online === null ? palette.textMuted : online ? palette.ok : palette.danger;

  return (
    <Screen title="More" back>
      <Card style={styles.profile}>
        <Spark size={52} />
        <View style={styles.profileMain}>
          <Text style={styles.name}>PersonalAi</Text>
          {pairing ? (
            <Text style={styles.line}>Device {pairing.deviceId.slice(0, 8).toUpperCase()}</Text>
          ) : null}
          <View style={styles.statusLine} accessible accessibilityLabel={statusText}>
            <StatusDot color={statusColor} />
            <Text style={styles.line}>{statusText}</Text>
          </View>
        </View>
      </Card>

      <ListSection title="Tools" stagger>
        <ListRow
          icon="sun"
          title="Today"
          subtitle="Important mail, deadlines and events"
          chevron
          onPress={() => router.push('/today')}
        />
        <ListRow
          icon="folder"
          title="Files"
          subtitle="Laptop folders and Google Drive"
          chevron
          onPress={() => router.push('/files')}
        />
        <ListRow
          icon="bell"
          title="Alerts"
          subtitle="Recent alerts and what to notify"
          chevron
          onPress={() => router.push('/alerts')}
        />
        <ListRow
          icon="clock"
          title="Chat history"
          subtitle="Search, rename and delete chats"
          chevron
          onPress={() => router.push('/history')}
        />
      </ListSection>

      <ListSection title="App">
        <ListRow
          icon="settings"
          title="Settings"
          subtitle="Pairing, bank SMS, appearance"
          chevron
          onPress={() => router.push('/settings')}
        />
      </ListSection>

      <Text style={styles.footer}>Nothing leaves your laptop without your fingerprint.</Text>
    </Screen>
  );
}
