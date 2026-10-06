// Bank-SMS filtering and upload. The native receiver applies the same filter before anything is
// stored, so only bank/UPI messages ever reach the queue or leave the phone. Never log bodies.
import { ApiError, OfflineError, type SmsPayload } from './api';

export const MAX_BATCH = 500;

const PREFIX = /^[A-Z]{2}-/;
const SUFFIX = /-[STPG]$/;

/** `AD-BOBTXN` / `JD-SBIUPI-S` / `bobsms` -> `BOBTXN` / `SBIUPI` / `BOBSMS`. Mirrors the server. */
export function normaliseSender(sender: string): string {
  return sender.trim().toUpperCase().replace(PREFIX, '').replace(SUFFIX, '');
}

export function isBankSender(sender: string, allowlist: readonly string[]): boolean {
  const name = normaliseSender(sender);
  return name.startsWith('BOB') || allowlist.some((entry) => normaliseSender(entry) === name);
}

export interface QueuedMessage extends SmsPayload {
  id: string;
}

export interface FlushDeps {
  peek: (limit: number) => Promise<QueuedMessage[]>;
  remove: (ids: string[]) => Promise<void>;
  post: (messages: SmsPayload[]) => Promise<unknown>;
}

export interface FlushResult {
  sent: number;
  /** Messages the server had not seen before (its `accepted` count); overlaps are not counted. */
  fresh: number;
  /** Messages the server refused one by one as invalid (422); they are dropped, not retried. */
  dropped: number;
  /** Why the flush stopped early; the queue keeps everything that was not accepted. */
  stoppedBy: 'offline' | 'rejected' | null;
}

/** The server's count of new messages in a batch; 0 when an older server does not report it. */
function acceptedOf(response: unknown): number {
  const accepted = (response as { accepted?: unknown } | null)?.accepted;
  return typeof accepted === 'number' && accepted > 0 ? accepted : 0;
}

function invalid(error: unknown): boolean {
  return error instanceof ApiError && error.status === 422;
}

/**
 * Send queued messages in batches of at most 500. An item leaves the queue only after a 2xx.
 * If the server rejects a batch as invalid, the batch is retried one message at a time so a
 * single malformed SMS is dropped instead of blocking the queue for good.
 */
export async function flushQueue({ peek, remove, post }: FlushDeps): Promise<FlushResult> {
  let sent = 0;
  let fresh = 0;
  let dropped = 0;
  const strip = ({ sender, body, received_at }: QueuedMessage): SmsPayload => ({
    sender,
    body,
    received_at,
  });
  for (;;) {
    const batch = await peek(MAX_BATCH);
    if (batch.length === 0) return { sent, fresh, dropped, stoppedBy: null };
    try {
      fresh += acceptedOf(await post(batch.map(strip)));
      await remove(batch.map((m) => m.id));
      sent += batch.length;
    } catch (error) {
      if (error instanceof OfflineError) return { sent, fresh, dropped, stoppedBy: 'offline' };
      if (!invalid(error)) {
        if (error instanceof ApiError) return { sent, fresh, dropped, stoppedBy: 'rejected' };
        throw error;
      }
      for (const message of batch) {
        try {
          fresh += acceptedOf(await post([strip(message)]));
          sent += 1;
        } catch (inner) {
          if (inner instanceof OfflineError) return { sent, fresh, dropped, stoppedBy: 'offline' };
          if (!invalid(inner)) {
            if (inner instanceof ApiError) return { sent, fresh, dropped, stoppedBy: 'rejected' };
            throw inner;
          }
          dropped += 1;
        }
        await remove([message.id]);
      }
    }
    if (batch.length < MAX_BATCH) return { sent, fresh, dropped, stoppedBy: null };
  }
}
