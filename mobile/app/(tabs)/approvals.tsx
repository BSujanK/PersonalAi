import { useCallback, useState } from 'react';
import { Text, View } from 'react-native';

import { Spark } from '../../src/components/brand/Spark';
import { ApprovalCard } from '../../src/components/chat/ApprovalCard';
import { Icon } from '../../src/components/Icon';
import { ResultLink } from '../../src/components/ResultLink';
import { Screen } from '../../src/components/Screen';
import { ErrorText, Loading, Stagger } from '../../src/components/ui';
import { listApprovals, type Approval } from '../../src/lib/api';
import { resultLink } from '../../src/lib/approvalFlow';
import { errorMessage } from '../../src/lib/format';
import { actionTitle } from '../../src/lib/toolLabels';
import { usePolling } from '../../src/lib/usePolling';
import { radius, space, type, useTheme, useThemedStyles, type Palette } from '../../src/theme';

const makeStyles = (p: Palette) => ({
  done: {
    backgroundColor: p.surface,
    borderRadius: radius.card,
    borderWidth: 1,
    borderColor: p.glassBorder,
    padding: space.md,
    gap: space.sm,
  },
  doneHead: { flexDirection: 'row' as const, alignItems: 'center' as const, gap: space.sm },
  doneTitle: { ...type.headline, color: p.text, flex: 1 },
  empty: { alignItems: 'center' as const, gap: space.sm, paddingVertical: space.xxl },
  emptyTitle: { ...type.title3, color: p.text },
  emptyText: { ...type.subheadline, color: p.textMuted, textAlign: 'center' as const },
});

export default function Approvals() {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  const [items, setItems] = useState<Approval[] | null>(null);
  const [refreshing, setRefreshing] = useState(false);
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

  const subtitle =
    items === null
      ? undefined
      : items.length === 0
        ? 'Nothing waiting'
        : `${items.length} waiting for you`;

  return (
    <Screen
      title="Approvals"
      subtitle={subtitle}
      tabs
      refreshing={refreshing}
      onRefresh={() => void refresh()}
    >
      <ErrorText message={error} />
      {items === null && !error ? <Loading /> : null}
      {links.map(({ id, tool, link }) => (
        <View key={`done:${id}`} style={styles.done}>
          <View style={styles.doneHead}>
            <Icon name="check-circle" size={20} color={palette.ok} />
            <Text style={styles.doneTitle}>{actionTitle(tool)}</Text>
          </View>
          <ResultLink link={link} />
        </View>
      ))}
      {items?.length === 0 && links.length === 0 ? (
        <View style={styles.empty}>
          <Spark size={56} />
          <Text style={styles.emptyTitle}>All clear</Text>
          <Text style={styles.emptyText}>
            When the agent wants to send, share or change something, it waits here for your
            fingerprint.
          </Text>
        </View>
      ) : null}
      {items?.map((item, i) => (
        <Stagger key={item.id} index={i}>
          <ApprovalCard
            actionId={item.id}
            initial={item}
            onDecided={(approval, result) => {
              const link = resultLink(result.result);
              if (link) {
                setLinks((prev) => [{ id: approval.id, tool: approval.tool_name, link }, ...prev]);
              }
              void load();
            }}
          />
        </Stagger>
      ))}
    </Screen>
  );
}
