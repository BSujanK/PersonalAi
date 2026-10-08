// Automatic bank-SMS import: whenever the app opens or comes back to the foreground, and in the
// background task. The first run reads the last 30 days; after that, only what arrived since the
// last successful import, with an hour of overlap (the server de-duplicates). It never asks for
// permission itself: without it, Settings shows one clear prompt instead.
import BankSms from '../../modules/bank-sms';
import { applyAllowlist, flushSmsQueue, hasSmsPermission } from './bankSms';
import { getJson, setJson } from './prefs';
import type { FlushResult } from './smsSync';

const DAY_MS = 86_400_000;
const HOUR_MS = 3_600_000;
export const FIRST_IMPORT_DAYS = 30;
export const OVERLAP_MS = HOUR_MS;

const LAST_KEY = 'sms.lastAutoImport';
const NO_PERMISSION_KEY = 'sms.permissionMissing';

export type AutoImportResult =
  | { status: 'synced'; queued: number; fresh: number; offline: boolean }
  | { status: 'no-permission' }
  | { status: 'busy' }
  | { status: 'failed' };

export interface AutoImportDeps {
  now: () => number;
  hasPermission: () => Promise<boolean>;
  prepare: () => Promise<void>;
  scan: (sinceMs: number) => Promise<number>;
  flush: () => Promise<FlushResult>;
  getLast: () => Promise<number | null>;
  setLast: (ms: number) => Promise<void>;
  setPermissionMissing: (missing: boolean) => Promise<void>;
}

/** Where a scan starts: 30 days back the first time, else the last import minus an hour. */
export function importSince(last: number | null, now: number): number {
  return last === null ? now - FIRST_IMPORT_DAYS * DAY_MS : Math.max(0, last - OVERLAP_MS);
}

let running: Promise<AutoImportResult> | null = null;

/** Test hook: forget an in-flight run. */
export function resetAutoImportForTests(): void {
  running = null;
}

async function run(deps: AutoImportDeps): Promise<AutoImportResult> {
  if (!(await deps.hasPermission())) {
    await deps.setPermissionMissing(true);
    // Payment-app notifications are queued without SMS permission; still upload what is queued.
    await deps.flush().catch(() => undefined);
    return { status: 'no-permission' };
  }
  await deps.setPermissionMissing(false);
  const startedAt = deps.now();
  try {
    await deps.prepare();
    const queued = await deps.scan(importSince(await deps.getLast(), startedAt));
    // Scanned messages sit in the on-phone queue even when the laptop is offline, so the import
    // itself succeeded; the upload retries on the next run.
    await deps.setLast(startedAt);
    const flushed = await deps.flush();
    return {
      status: 'synced',
      queued,
      fresh: flushed.fresh,
      offline: flushed.stoppedBy === 'offline',
    };
  } catch {
    return { status: 'failed' };
  }
}

/**
 * Import and upload new bank SMS. Never throws, never blocks the caller's UI, and runs at most
 * once at a time (a second call while one is running gets `busy`).
 */
export function autoImportBankSms(deps: AutoImportDeps = DEFAULT_DEPS): Promise<AutoImportResult> {
  if (running) return Promise.resolve({ status: 'busy' });
  running = run(deps).finally(() => {
    running = null;
  });
  return running;
}

/** True when the last automatic import found no SMS permission; Settings shows a prompt. */
export const smsPermissionMissing = () => getJson<boolean>(NO_PERMISSION_KEY, false);

const DEFAULT_DEPS: AutoImportDeps = {
  now: () => Date.now(),
  hasPermission: hasSmsPermission,
  prepare: applyAllowlist,
  scan: (sinceMs) => BankSms.scanInbox(sinceMs),
  flush: flushSmsQueue,
  getLast: () => getJson<number | null>(LAST_KEY, null),
  setLast: (ms) => setJson(LAST_KEY, ms),
  setPermissionMissing: (missing) => setJson(NO_PERMISSION_KEY, missing),
};
