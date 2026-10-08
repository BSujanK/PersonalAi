import {
  autoImportBankSms,
  FIRST_IMPORT_DAYS,
  importSince,
  OVERLAP_MS,
  resetAutoImportForTests,
  type AutoImportDeps,
} from '../smsAutoImport';

jest.mock('../../../modules/bank-sms', () => ({}));
jest.mock('../bankSms', () => ({}));

const NOW = Date.UTC(2026, 9, 6, 12, 0, 0);
const DAY = 86_400_000;

function deps(over: Partial<AutoImportDeps> = {}) {
  let last: number | null = null;
  const d = {
    now: () => NOW,
    hasPermission: jest.fn(async () => true),
    prepare: jest.fn(async () => undefined),
    scan: jest.fn(async () => 2),
    flush: jest.fn(async () => ({ sent: 2, fresh: 1, dropped: 0, stoppedBy: null as null })),
    getLast: jest.fn(async () => last),
    setLast: jest.fn(async (ms: number) => {
      last = ms;
    }),
    setPermissionMissing: jest.fn(async () => undefined),
    ...over,
  };
  return d satisfies AutoImportDeps;
}

beforeEach(resetAutoImportForTests);

describe('importSince', () => {
  it('reads the last 30 days the first time, then since the last import minus an hour', () => {
    expect(importSince(null, NOW)).toBe(NOW - FIRST_IMPORT_DAYS * DAY);
    expect(importSince(NOW - 5 * 60_000, NOW)).toBe(NOW - 5 * 60_000 - OVERLAP_MS);
  });
});

describe('autoImportBankSms', () => {
  it('imports, records the start time and reports only new messages', async () => {
    const d = deps();
    const result = await autoImportBankSms(d);
    expect(d.scan).toHaveBeenCalledWith(NOW - 30 * DAY);
    expect(d.setLast).toHaveBeenCalledWith(NOW);
    expect(result).toEqual({ status: 'synced', queued: 2, fresh: 1, offline: false });
    // The next run starts an hour before the last one.
    await autoImportBankSms(d);
    expect(d.scan).toHaveBeenLastCalledWith(NOW - OVERLAP_MS);
  });

  it('never asks for permission; it flags it for Settings instead', async () => {
    const d = deps({ hasPermission: jest.fn(async () => false) });
    expect(await autoImportBankSms(d)).toEqual({ status: 'no-permission' });
    expect(d.setPermissionMissing).toHaveBeenCalledWith(true);
    expect(d.scan).not.toHaveBeenCalled();
    // Queued payment-app notifications still go up.
    expect(d.flush).toHaveBeenCalled();
  });

  it('runs once at a time', async () => {
    let release: () => void = () => undefined;
    const scan = jest.fn(() => new Promise<number>((r) => (release = () => r(0))));
    const d = deps({ scan });
    const first = autoImportBankSms(d);
    expect(await autoImportBankSms(d)).toEqual({ status: 'busy' });
    for (let i = 0; i < 20 && scan.mock.calls.length === 0; i += 1) await Promise.resolve();
    release();
    expect((await first).status).toBe('synced');
  });

  it('does not move the marker when the scan fails, and never throws', async () => {
    const d = deps({ scan: jest.fn(async () => Promise.reject(new Error('boom'))) });
    expect(await autoImportBankSms(d)).toEqual({ status: 'failed' });
    expect(d.setLast).not.toHaveBeenCalled();
  });

  it('keeps the marker when the laptop is offline: the messages are queued on the phone', async () => {
    const d = deps({
      flush: jest.fn(async () => ({
        sent: 0,
        fresh: 0,
        dropped: 0,
        stoppedBy: 'offline' as const,
      })),
    });
    expect(await autoImportBankSms(d)).toEqual({
      status: 'synced',
      queued: 2,
      fresh: 0,
      offline: true,
    });
    expect(d.setLast).toHaveBeenCalledWith(NOW);
  });
});
