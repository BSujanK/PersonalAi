import { useState } from 'react';
import { Text, View } from 'react-native';

import { Spark } from '../../src/components/brand/Spark';
import { ApprovalCard } from '../../src/components/chat/ApprovalCard';
import { Icon } from '../../src/components/Icon';
import { ResultLink } from '../../src/components/ResultLink';
import { Screen } from '../../src/components/Screen';
import { SkeletonRows } from '../../src/components/Skeleton';
import { LoadFailed, StaleNote, Stagger } from '../../src/components/ui';
import { listApprovals } from '../../src/lib/api';
import { resultLink } from '../../src/lib/approvalFlow';
import { errorMessage } from '../../src/lib/format';
import { actionTitle } from '../../src/lib/toolLabels';
import { useLoader, usePullToRefresh } from '../../src/lib/usePolling';
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
  const { data: items, error, loading, failing, reload } = useLoader(listApprovals);
  const pull = usePullToRefresh(reload);
  const [links, setLinks] = useState<{ id: string; tool: string; link: string }[]>([]);

  const subtitle =
    items === null
      ? undefined
      : items.length === 0
        ? 'Nothing waiting'
        : `${items.length} waiting for you`;

  return (
    <Screen title="Approvals" subtitle={subtitle} tabs {...pull}>
      {failing && items ? <StaleNote /> : null}
      {failing && !items ? <LoadFailed what="approvals" reason={errorMessage(error)} /> : null}
      {loading ? <SkeletonRows count={2} /> : null}
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
            When the agent wants to send, share or change something, or set a reminder, alarm or
            timer, it waits here for your fingerprint.
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
              void reload();
            }}
          />
        </Stagger>
      ))}
    </Screen>
  );
}
