import { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Text, View } from 'react-native';

import { getApproval, type Approval } from '../../lib/api';
import {
  decideWithBiometrics,
  outcomeOf,
  resultLink,
  type ApprovalOutcome,
  type Decision,
} from '../../lib/approvalFlow';
import { errorMessage, timeLeft } from '../../lib/format';
import { onRefresh } from '../../lib/refreshBus';
import { toolLabel } from '../../lib/toolLabels';
import { fontFamily, size, useTheme, useThemedStyles, type Palette } from '../../theme';
import { Icon, type IconName } from '../Icon';
import { ResultLink } from '../ResultLink';
import { Button, ErrorText } from '../ui';

const makeStyles = (p: Palette) => ({
  card: {
    backgroundColor: p.surface,
    borderColor: p.border,
    borderWidth: 1,
    borderRadius: 16,
    overflow: 'hidden' as const,
  },
  header: {
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    gap: 10,
    padding: 14,
    paddingBottom: 10,
  },
  headerText: { flex: 1 },
  kicker: { fontFamily: fontFamily.bodyMedium, fontSize: size.caption + 1, color: p.textMuted },
  title: { fontFamily: fontFamily.bodySemiBold, fontSize: size.body, color: p.text },
  previewWell: {
    marginHorizontal: 14,
    padding: 12,
    borderRadius: 10,
    backgroundColor: p.muted,
  },
  preview: { fontFamily: fontFamily.mono, fontSize: size.small, lineHeight: 20, color: p.text },
  actions: { flexDirection: 'row' as const, gap: 10, padding: 14 },
  action: { flex: 1 },
  footer: { padding: 14, gap: 6 },
  result: { flexDirection: 'row' as const, alignItems: 'center' as const, gap: 8 },
  resultText: { fontFamily: fontFamily.bodyMedium, fontSize: size.body - 1, color: p.text },
  hint: { fontFamily: fontFamily.body, fontSize: size.small, color: p.textMuted },
});

const RESULT: Record<Exclude<ApprovalOutcome, 'pending'>, { icon: IconName; text: string }> = {
  approved: { icon: 'check-circle', text: 'Approved' },
  rejected: { icon: 'x-circle', text: 'Rejected' },
  failed: { icon: 'alert-circle', text: 'Approved, but the action failed to run' },
  expired: { icon: 'clock', text: 'Expired. Ask again to get a fresh proposal.' },
};

/**
 * A permission-style card for one proposed action. It shows the exact preview the server stored
 * and decides through the same biometric signing flow as the Approvals screen.
 */
export function ApprovalCard({ actionId }: { actionId: string }) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  const [approval, setApproval] = useState<Approval | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Decision | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [decidedStatus, setDecidedStatus] = useState<string | null>(null);
  const [link, setLink] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const mounted = useRef(true);

  useEffect(() => {
    let cancelled = false;
    const run = () => {
      getApproval(actionId).then(
        (item) => {
          if (cancelled) return;
          setApproval(item);
          setDecidedStatus(null); // the stored status is authoritative once we have it
          setLoadError(null);
        },
        (e: unknown) => {
          if (!cancelled) setLoadError(errorMessage(e));
        },
      );
    };
    run();
    const unsubscribe = onRefresh(run);
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, [actionId, reloadKey]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const reload = () => setReloadKey((k) => k + 1);

  async function decide(decision: Decision) {
    if (!approval || busy) return;
    setBusy(decision);
    setError(null);
    try {
      const result = await decideWithBiometrics(approval, decision);
      if (mounted.current) {
        setDecidedStatus(result.status);
        setLink(resultLink(result.result));
        reload();
      }
    } catch (e) {
      // A cancelled or failed biometric prompt lands here too; nothing was sent in that case.
      if (mounted.current) setError(errorMessage(e));
    } finally {
      if (mounted.current) setBusy(null);
    }
  }

  if (!approval) {
    return (
      <View style={styles.card}>
        <View style={styles.header}>
          <Icon name="shield" size={20} color={palette.accent} />
          <View style={styles.headerText}>
            <Text style={styles.kicker}>Approval</Text>
            <Text style={styles.title}>
              {loadError ? 'Could not load this approval' : 'Loading the proposal...'}
            </Text>
          </View>
          {loadError ? null : <ActivityIndicator color={palette.accent} />}
        </View>
        {loadError ? (
          <View style={styles.footer}>
            <ErrorText message={loadError} />
            <Button label="Try again" tone="plain" onPress={reload} />
          </View>
        ) : null}
      </View>
    );
  }

  const outcome = outcomeOf(decidedStatus ?? approval.status, approval.expires_at);
  const final = outcome !== 'pending';
  return (
    <View
      style={styles.card}
      accessibilityLabel={`Approval request: ${toolLabel(approval.tool_name)}`}
    >
      <View style={styles.header}>
        <Icon name="shield" size={20} color={palette.accent} />
        <View style={styles.headerText}>
          <Text style={styles.kicker}>
            {final ? 'Approval' : `Approval needed - ${timeLeft(approval.expires_at)}`}
          </Text>
          <Text style={styles.title}>{toolLabel(approval.tool_name)}</Text>
        </View>
      </View>
      <View style={styles.previewWell}>
        <Text selectable style={styles.preview}>
          {approval.preview}
        </Text>
      </View>
      {final ? (
        <View style={styles.footer}>
          <View style={styles.result}>
            <Icon
              name={RESULT[outcome].icon}
              size={20}
              color={
                outcome === 'approved'
                  ? palette.ok
                  : outcome === 'rejected'
                    ? palette.textMuted
                    : palette.danger
              }
            />
            <Text style={styles.resultText}>{RESULT[outcome].text}</Text>
          </View>
          {outcome === 'approved' && link ? <ResultLink link={link} /> : null}
          <ErrorText message={error} />
        </View>
      ) : (
        <>
          <View style={styles.actions}>
            <View style={styles.action}>
              <Button
                label="Reject"
                tone="plain"
                accessibilityLabel="Reject this action"
                onPress={() => void decide('reject')}
                disabled={busy !== null}
              />
            </View>
            <View style={styles.action}>
              <Button
                label={busy === 'approve' ? 'Waiting...' : 'Approve'}
                accessibilityLabel="Approve this action"
                onPress={() => void decide('approve')}
                disabled={busy !== null}
              />
            </View>
          </View>
          <View style={[styles.footer, { paddingTop: 0 }]}>
            <Text style={styles.hint}>Approving asks for your fingerprint or face.</Text>
            <ErrorText message={error} />
          </View>
        </>
      )}
    </View>
  );
}
