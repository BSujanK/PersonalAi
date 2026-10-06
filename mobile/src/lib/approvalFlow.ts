// The one place a decision is signed and sent. Used by the inline approval card in the chat and
// by the Approvals screen, so both go through the same biometric prompt (CLAUDE.md rule 1).
import { decideApproval, type Approval, type DecisionResult } from './api';
import { processDeviceCommands } from './deviceCommands';
import { emitRefresh } from './refreshBus';
import { signWithBiometrics } from './secureKeys';
import { toolLabel } from './toolLabels';

export type Decision = 'approve' | 'reject';

/**
 * Prompt for biometrics, sign (action id | payload hash | nonce | decision) with the approval key
 * and post the decision. Throws if the prompt is cancelled or the agent refuses; in the cancelled
 * case nothing was sent. Never sends anything the user did not see in the preview.
 */
export async function decideWithBiometrics(
  approval: Approval,
  decision: Decision,
): Promise<DecisionResult> {
  const verb = decision === 'approve' ? 'Approve' : 'Reject';
  const sig = await signWithBiometrics(
    {
      actionId: approval.id,
      payloadHash: approval.payload_hash,
      nonce: approval.nonce,
      decision,
    },
    `${verb}: ${toolLabel(approval.tool_name)}`,
  );
  const result = await decideApproval(approval.id, decision, {
    payload_hash: approval.payload_hash,
    nonce: approval.nonce,
    sig,
  });
  if (decision === 'approve') await processDeviceCommands().catch(() => undefined);
  emitRefresh();
  return result;
}

/** The shareable link in an executed action's result, only if it is an https URL. */
export function resultLink(result: unknown): string | null {
  if (typeof result !== 'object' || result === null) return null;
  const link = (result as { link?: unknown }).link;
  return typeof link === 'string' && link.startsWith('https://') ? link : null;
}

export type ApprovalOutcome = 'pending' | 'approved' | 'rejected' | 'failed' | 'expired';

/** Collapse the server's status into what the card shows. */
export function outcomeOf(
  status: string,
  expiresAt: string,
  now: number = Date.now(),
): ApprovalOutcome {
  switch (status) {
    case 'pending':
      return Date.parse(expiresAt) <= now ? 'expired' : 'pending';
    case 'approved':
    case 'executed':
      return 'approved';
    case 'rejected':
      return 'rejected';
    case 'failed':
      return 'failed';
    default:
      return 'expired';
  }
}
