import { useCallback, useState } from 'react';
import { Text, View } from 'react-native';

import { ResultLink } from '../../src/components/ResultLink';
import { Body, Button, Card, ErrorText } from '../../src/components/ui';
import { Screen } from '../../src/components/Screen';
import { listApprovals, type Approval } from '../../src/lib/api';
import { decideWithBiometrics, resultLink } from '../../src/lib/approvalFlow';
import { errorMessage, timeLeft } from '../../src/lib/format';
import { toolLabel } from '../../src/lib/toolLabels';
import { usePolling } from '../../src/lib/usePolling';
import { fontFamily, size, useThemedStyles, type Palette } from '../../src/theme';

const makeStyles = (p: Palette) => ({
  tool: { fontFamily: fontFamily.bodySemiBold, fontSize: size.body, color: p.text },
  preview: {
    fontFamily: fontFamily.mono,
    fontSize: size.small,
    lineHeight: 20,
    color: p.text,
    backgroundColor: p.muted,
    borderRadius: 10,
    padding: 12,
    marginVertical: 8,
  },
  actions: { flexDirection: 'row' as const, gap: 10 },
  flex: { flex: 1 },
});

export default function Approvals() {
  const styles = useThemedStyles(makeStyles);
  const [items, setItems] = useState<Approval[] | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [links, setLinks] = useState<{ id: string; tool: string; link: string }[]>([]);

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
      const result = await decideWithBiometrics(item, decision); // also refreshes every screen
      const link = resultLink(result.result);
      if (link) setLinks((prev) => [{ id: item.id, tool: item.tool_name, link }, ...prev]);
    } catch (e) {
      // A cancelled or failed biometric prompt lands here too; nothing was sent in that case.
      setError(errorMessage(e));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <Screen title="Approvals" menu refreshing={refreshing} onRefresh={() => void refresh()}>
      <ErrorText message={error} />
      {links.map(({ id, tool, link }) => (
        <Card key={`done:${id}`}>
          <Text style={styles.tool}>{toolLabel(tool)}</Text>
          <Body muted>Approved and done.</Body>
          <ResultLink link={link} />
        </Card>
      ))}
      {items?.length === 0 ? <Body muted>Nothing waiting for approval.</Body> : null}
      {items?.map((item) => (
        <Card key={item.id}>
          <Text style={styles.tool}>{toolLabel(item.tool_name)}</Text>
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
