import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { ActivityIndicator, Text, View } from 'react-native';
import Animated, { FadeIn } from 'react-native-reanimated';

import { parsePreview, recipientWarnings } from '../../lib/actionPreview';
import { getApproval, type Approval, type DecisionResult } from '../../lib/api';
import {
  decideWithBiometrics,
  outcomeOf,
  resultLink,
  type ApprovalOutcome,
  type Decision,
} from '../../lib/approvalFlow';
import { errorMessage, expiresWithin, timeLeft } from '../../lib/format';
import { haptics } from '../../lib/haptics';
import { onRefresh } from '../../lib/refreshBus';
import { actionTitle } from '../../lib/toolLabels';
import {
  fontFamily,
  motion,
  radius,
  space,
  type,
  useTheme,
  useThemedStyles,
  type Palette,
} from '../../theme';
import { ActionPreview } from '../approval/ActionPreview';
import { Icon, type IconName } from '../Icon';
import { ResultLink } from '../ResultLink';
import { Badge, Button, ErrorText } from '../ui';

const SOON_MS = 3 * 60_000;

const makeStyles = (p: Palette) => ({
  card: {
    backgroundColor: p.surface,
    borderRadius: radius.card,
    borderWidth: 1,
    borderColor: p.border,
    overflow: 'hidden' as const,
  },
  header: {
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    gap: space.sm + space.xs,
    padding: space.md,
    paddingBottom: space.sm + space.xs,
  },
  tile: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
    backgroundColor: p.accentSoft,
  },
  headerText: { flex: 1, gap: 2 },
  kicker: { ...type.footnote, fontFamily: fontFamily.bodyMedium, color: p.textMuted },
  title: { ...type.headline, color: p.text },
  badges: {
    flexDirection: 'row' as const,
    flexWrap: 'wrap' as const,
    gap: space.sm,
    paddingHorizontal: space.md,
    paddingBottom: space.sm + space.xs,
  },
  body: { paddingHorizontal: space.md },
  actions: { flexDirection: 'row' as const, gap: space.sm + space.xs, padding: space.md },
  action: { flex: 1 },
  footer: { padding: space.md, gap: space.sm },
  result: { flexDirection: 'row' as const, alignItems: 'center' as const, gap: space.sm },
  resultText: { ...type.callout, fontFamily: fontFamily.bodyMedium, color: p.text, flex: 1 },
  hint: { ...type.footnote, color: p.textMuted, textAlign: 'center' as const },
  withHint: { gap: space.sm },
});

const RESULT: Record<Exclude<ApprovalOutcome, 'pending'>, { icon: IconName; text: string }> = {
  approved: { icon: 'check-circle', text: 'Approved and done' },
  rejected: { icon: 'x-circle', text: 'Rejected. Nothing was sent.' },
  failed: { icon: 'alert-circle', text: 'Approved, but the action failed to run' },
  expired: { icon: 'clock', text: 'Expired. Ask again to get a fresh proposal.' },
};

/** Phone actions get their own mark in the card; everything else is the shield. */
const ACTION_ICONS: Record<string, IconName> = {
  phone_set_alarm: 'clock',
  phone_set_timer: 'watch',
  phone_reminder: 'bell',
};

// Built once: the outcome row is content the owner is waiting on, so it eases in (220 ms).
const OUTCOME_ENTER = FadeIn.duration(motion.enterMs);

/**
 * A permission-style card for one proposed action: who it goes to (with NEW and EXTERNAL
 * badges), what is attached, the link scope, and the exact preview the server stored. Approve
 * and Reject go through the one biometric signing flow (approvalFlow.decideWithBiometrics).
 */
export function ApprovalCard({
  actionId,
  initial,
  onDecided,
  hint,
}: {
  actionId: string;
  /** Already-fetched approval (the Approvals screen); skips the first fetch. */
  initial?: Approval;
  onDecided?: (approval: Approval, result: DecisionResult) => void;
  /** Shown under the card while it still waits for a decision (the chat's "also in Approvals"). */
  hint?: ReactNode;
}) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  const [approval, setApproval] = useState<Approval | null>(initial ?? null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Decision | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [decidedStatus, setDecidedStatus] = useState<string | null>(null);
  const [link, setLink] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const mounted = useRef(true);
  const skipFirst = useRef(initial !== undefined);

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
    if (skipFirst.current) skipFirst.current = false;
    else run();
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

  const warnings = useMemo(
    () =>
      approval
        ? recipientWarnings(parsePreview(approval.tool_name, approval.preview).recipients)
        : { fresh: 0, external: 0 },
    [approval],
  );

  const reload = () => setReloadKey((k) => k + 1);

  async function decide(decision: Decision) {
    if (!approval || busy) return;
    setBusy(decision);
    setError(null);
    try {
      const result = await decideWithBiometrics(approval, decision);
      if (decision === 'approve' && result.status === 'failed') haptics.error();
      else haptics.success();
      onDecided?.(approval, result);
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
          <View style={styles.tile}>
            <Icon name="shield" size={18} color={palette.accentText} />
          </View>
          <View style={styles.headerText}>
            <Text style={styles.kicker}>Approval</Text>
            <Text style={styles.title}>
              {loadError ? 'Could not load this approval' : 'Loading the proposal…'}
            </Text>
          </View>
          {loadError ? null : <ActivityIndicator color={palette.accentText} />}
        </View>
        {loadError ? (
          <View style={styles.footer}>
            <ErrorText message={loadError} />
            <Button label="Try again" tone="plain" compact onPress={reload} />
          </View>
        ) : null}
      </View>
    );
  }

  const outcome = outcomeOf(decidedStatus ?? approval.status, approval.expires_at);
  const final = outcome !== 'pending';
  const soon = !final && expiresWithin(approval.expires_at, SOON_MS);
  const card = (
    <View
      style={styles.card}
      accessibilityLabel={`Approval request: ${actionTitle(approval.tool_name)}`}
    >
      <View style={styles.header}>
        <View style={styles.tile}>
          <Icon
            name={ACTION_ICONS[approval.tool_name] ?? 'shield'}
            size={18}
            color={palette.accentText}
          />
        </View>
        <View style={styles.headerText}>
          <Text style={[styles.kicker, soon && { color: palette.warn }]}>
            {final ? 'Approval' : `Needs your approval · ${timeLeft(approval.expires_at)}`}
          </Text>
          <Text style={styles.title}>{actionTitle(approval.tool_name)}</Text>
        </View>
      </View>
      {warnings.fresh || warnings.external ? (
        <View style={styles.badges}>
          {warnings.fresh ? (
            <Badge
              label={`${warnings.fresh} NEW`}
              tone="warn"
              icon="alert-triangle"
              spoken={`${warnings.fresh} recipient${warnings.fresh === 1 ? '' : 's'} you have never emailed`}
            />
          ) : null}
          {warnings.external ? (
            <Badge
              label={`${warnings.external} EXTERNAL`}
              tone="danger"
              icon="globe"
              spoken={`${warnings.external} recipient${warnings.external === 1 ? '' : 's'} outside your domains`}
            />
          ) : null}
        </View>
      ) : null}
      <View style={styles.body}>
        <ActionPreview toolName={approval.tool_name} preview={approval.preview} />
      </View>
      {final ? (
        <Animated.View entering={OUTCOME_ENTER} style={styles.footer}>
          <View style={styles.result} accessibilityLiveRegion="polite">
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
        </Animated.View>
      ) : (
        <>
          <View style={styles.actions}>
            <View style={styles.action}>
              <Button
                label={busy === 'reject' ? 'Waiting…' : 'Reject'}
                tone="plain"
                accessibilityLabel="Reject this action"
                onPress={() => void decide('reject')}
                disabled={busy !== null}
              />
            </View>
            <View style={styles.action}>
              <Button
                label={busy === 'approve' ? 'Waiting…' : 'Approve'}
                icon="lock"
                accessibilityLabel="Approve this action"
                accessibilityHint="Asks for your fingerprint or face"
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
  if (hint === undefined) return card;
  return (
    <View style={styles.withHint}>
      {card}
      {final ? null : hint}
    </View>
  );
}
