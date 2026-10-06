import { ApiError, OfflineError } from '../api';
import {
  flushQueue,
  isBankSender,
  MAX_BATCH,
  normaliseSender,
  type QueuedMessage,
} from '../smsSync';

jest.mock('../secureKeys', () => ({ loadPairing: jest.fn() }));

describe('normaliseSender', () => {
  it.each([
    ['AD-BOBTXN', 'BOBTXN'],
    ['JD-SBIUPI-S', 'SBIUPI'],
    ['bobsms', 'BOBSMS'],
    ['  VM-HDFCBK-T ', 'HDFCBK'],
    ['+919999900000', '+919999900000'],
  ])('%s -> %s', (input, expected) => {
    expect(normaliseSender(input)).toBe(expected);
  });
});

describe('isBankSender', () => {
  const allowlist = ['SBIUPI', 'HDFCBK'];

  it('accepts allowlisted senders in any carrier form', () => {
    expect(isBankSender('JD-SBIUPI-S', allowlist)).toBe(true);
    expect(isBankSender('hdfcbk', allowlist)).toBe(true);
  });

  it('accepts anything starting with BOB', () => {
    expect(isBankSender('AD-BOBTXN', [])).toBe(true);
    expect(isBankSender('bobsms', [])).toBe(true);
  });

  it('rejects everything else', () => {
    expect(isBankSender('AX-AMAZON', allowlist)).toBe(false);
    expect(isBankSender('+919999900000', allowlist)).toBe(false);
  });
});

function makeQueue(count: number) {
  const items: QueuedMessage[] = Array.from({ length: count }, (_, i) => ({
    id: `id${i}`,
    sender: 'AD-BOBTXN',
    body: `synthetic ${i}`,
    received_at: 1_700_000_000_000 + i,
  }));
  return {
    items,
    peek: async (limit: number) => items.slice(0, limit),
    remove: async (ids: string[]) => {
      for (const id of ids)
        items.splice(
          items.findIndex((m) => m.id === id),
          1,
        );
    },
  };
}

describe('flushQueue', () => {
  it('removes items only after a successful post', async () => {
    const q = makeQueue(3);
    const post = jest.fn().mockResolvedValue({});
    await expect(flushQueue({ ...q, post })).resolves.toEqual({
      sent: 3,
      fresh: 0,
      dropped: 0,
      stoppedBy: null,
    });
    expect(post).toHaveBeenCalledTimes(1);
    expect(post.mock.calls[0][0]).toEqual([
      { sender: 'AD-BOBTXN', body: 'synthetic 0', received_at: 1_700_000_000_000 },
      { sender: 'AD-BOBTXN', body: 'synthetic 1', received_at: 1_700_000_000_001 },
      { sender: 'AD-BOBTXN', body: 'synthetic 2', received_at: 1_700_000_000_002 },
    ]);
    expect(q.items).toHaveLength(0);
  });

  it('keeps everything and stops when offline', async () => {
    const q = makeQueue(3);
    const post = jest.fn().mockRejectedValue(new OfflineError());
    await expect(flushQueue({ ...q, post })).resolves.toEqual({
      sent: 0,
      fresh: 0,
      dropped: 0,
      stoppedBy: 'offline',
    });
    expect(q.items).toHaveLength(3);
  });

  it('keeps everything on a 5xx', async () => {
    const q = makeQueue(2);
    const post = jest.fn().mockRejectedValue(new ApiError(503, 'unavailable'));
    await expect(flushQueue({ ...q, post })).resolves.toEqual({
      sent: 0,
      fresh: 0,
      dropped: 0,
      stoppedBy: 'rejected',
    });
    expect(q.items).toHaveLength(2);
  });

  it('sends batches of at most 500 and keeps the unsent rest after a failure', async () => {
    const q = makeQueue(MAX_BATCH + 20);
    const post = jest.fn().mockResolvedValueOnce({}).mockRejectedValueOnce(new OfflineError());
    await expect(flushQueue({ ...q, post })).resolves.toEqual({
      sent: MAX_BATCH,
      fresh: 0,
      dropped: 0,
      stoppedBy: 'offline',
    });
    expect(post.mock.calls[0][0]).toHaveLength(MAX_BATCH);
    expect(q.items).toHaveLength(20);
  });

  it('drains a queue larger than one batch', async () => {
    const q = makeQueue(MAX_BATCH + 20);
    const post = jest.fn().mockResolvedValue({});
    await expect(flushQueue({ ...q, post })).resolves.toEqual({
      sent: MAX_BATCH + 20,
      fresh: 0,
      dropped: 0,
      stoppedBy: null,
    });
    expect(post.mock.calls.map((c) => c[0].length)).toEqual([MAX_BATCH, 20]);
  });

  it('does nothing for an empty queue', async () => {
    const post = jest.fn();
    await expect(flushQueue({ ...makeQueue(0), post })).resolves.toEqual({
      sent: 0,
      fresh: 0,
      dropped: 0,
      stoppedBy: null,
    });
    expect(post).not.toHaveBeenCalled();
  });

  it('drops only the messages the server refuses one by one as invalid', async () => {
    const q = makeQueue(3);
    const post = jest
      .fn()
      .mockRejectedValueOnce(new ApiError(422, 'invalid received_at'))
      .mockResolvedValueOnce({})
      .mockRejectedValueOnce(new ApiError(422, 'invalid received_at'))
      .mockResolvedValueOnce({});
    await expect(flushQueue({ ...q, post })).resolves.toEqual({
      sent: 2,
      fresh: 0,
      dropped: 1,
      stoppedBy: null,
    });
    expect(post.mock.calls.slice(1).map((c) => c[0].length)).toEqual([1, 1, 1]);
    expect(q.items).toHaveLength(0);
  });
});

describe('flushQueue counts only messages new to the server', () => {
  it('sums the server accepted count and ignores duplicates', async () => {
    const queue = [
      { id: 'a', sender: 'BOBTXN', body: 'one', received_at: 1 },
      { id: 'b', sender: 'BOBTXN', body: 'two', received_at: 2 },
    ];
    const result = await flushQueue({
      peek: async () => queue.splice(0, queue.length),
      remove: async () => undefined,
      post: async () => ({ accepted: 1, duplicates: 1 }),
    });
    expect(result).toEqual({ sent: 2, fresh: 1, dropped: 0, stoppedBy: null });
  });
});
