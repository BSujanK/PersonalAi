import { useCallback, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { Body, Button, Card, ErrorText, Screen, Title } from '../../src/components/ui';
import { decideApproval, listApprovals, type Approval } from '../../src/lib/api';
import { processDeviceCommands } from '../../src/lib/deviceCommands';
import { errorMessage, timeLeft } from '../../src/lib/format';
import { emitRefresh } from '../../src/lib/refreshBus';
import { signWithBiometrics } from '../../src/lib/secureKeys';
import { usePolling } from '../../src/lib/usePolling';

export default function Approvals() {
  const [items, setItems] = useState<Approval[] | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setItems(await listApprovals());
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);

  usePolling(load);

  async function refresh() {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }

  async function decide(item: Approval, decision: 'approve' | 'reject') {
    setBusyId(item.id);
    setError(null);
    try {
      const sig = await signWithBiometrics(
        { actionId: item.id, payloadHash: item.payload_hash, nonce: item.nonce, decision },
        `${decision === 'approve' ? 'Approve' : 'Reject'}: ${item.tool_name}`,
      );
      await decideApproval(item.id, decision, {
        payload_hash: item.payload_hash,
        nonce: item.nonce,
        sig,
      });
      if (decision === 'approve') await processDeviceCommands().catch(() => undefined);
      emitRefresh();
    } catch (e) {
      // A cancelled or failed biometric prompt lands here too; nothing was sent in that case.
      setError(errorMessage(e));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <Screen refreshing={refreshing} onRefresh={() => void refresh()}>
      <Title>Approvals</Title>
      <ErrorText message={error} />
      {items?.length === 0 ? <Body muted>Nothing waiting for approval.</Body> : null}
      {items?.map((item) => (
        <Card key={item.id}>
          <Text style={styles.tool}>{item.tool_name}</Text>
          <Body muted>{timeLeft(item.expires_at)}</Body>
          <Text selectable style={styles.preview}>
            {item.preview}
          </Text>
          <View style={styles.actions}>
            <View style={styles.flex}>
              <Button
                label="Approve"
                onPress={() => void decide(item, 'approve')}
                disabled={busyId !== null}
              />
            </View>
            <View style={styles.flex}>
              <Button
                label="Reject"
                tone="danger"
                onPress={() => void decide(item, 'reject')}
                disabled={busyId !== null}
              />
            </View>
          </View>
        </Card>
      ))}
    </Screen>
  );
}

const styles = StyleSheet.create({
  tool: { fontSize: 16, fontWeight: '700' },
  preview: { fontFamily: 'monospace', fontSize: 13, paddingVertical: 8 },
  actions: { flexDirection: 'row', gap: 8 },
  flex: { flex: 1 },
});
