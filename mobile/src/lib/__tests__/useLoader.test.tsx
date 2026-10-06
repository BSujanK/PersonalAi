import { act, renderHook } from '@testing-library/react-native';

import { ApiError } from '../api';
import { isRetryable, useLoader } from '../usePolling';

const mockTabPressed = new Set<() => void>();
const mockNavigation = {
  addListener: (_type: 'tabPress', listener: () => void) => {
    mockTabPressed.add(listener);
    return () => {
      mockTabPressed.delete(listener);
    };
  },
};
jest.mock('expo-router', () => ({
  useNavigation: () => mockNavigation,
  // Like the real hook: runs the effect while mounted and again when its callback changes.
  useFocusEffect: (effect: () => void | (() => void)) => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    require('react').useEffect(effect, [effect]);
  },
}));

// Isolate the retry timer from the 30s poll.
const QUIET = { intervalMs: 3_600_000 };

const flush = () =>
  act(async () => {
    await Promise.resolve();
  });
const advance = (ms: number) =>
  act(async () => {
    jest.advanceTimersByTime(ms);
  });

beforeEach(() => {
  jest.useFakeTimers();
  mockTabPressed.clear();
});
afterEach(() => jest.useRealTimers());

describe('useLoader', () => {
  it('loads when the screen appears: loading first, then the data', async () => {
    let answer: (value: { n: number }) => void = () => undefined;
    const fetcher = jest.fn(() => new Promise<{ n: number }>((resolve) => (answer = resolve)));
    const { result } = await renderHook(() => useLoader(fetcher, QUIET));
    expect(result.current).toMatchObject({ data: null, loading: true, failing: false });
    await act(async () => answer({ n: 1 }));
    expect(result.current).toMatchObject({
      data: { n: 1 },
      error: null,
      loading: false,
      failing: false,
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('keeps the last good data when a refresh fails, and recovers on the next success', async () => {
    const fetcher = jest.fn().mockResolvedValueOnce({ n: 1 }).mockRejectedValueOnce(new Error('x'));
    const { result } = await renderHook(() => useLoader(fetcher, QUIET));
    await flush();
    await act(async () => {
      await result.current.reload();
    });
    expect(result.current).toMatchObject({ data: { n: 1 }, loading: false, failing: true });
    expect(result.current.error).toEqual(new Error('x'));

    fetcher.mockResolvedValue({ n: 2 });
    await act(async () => {
      await result.current.reload();
    });
    expect(result.current).toMatchObject({ data: { n: 2 }, error: null, failing: false });
  });

  it('with no data yet, a failure is failing and not loading', async () => {
    const fetcher = jest.fn().mockRejectedValue(new Error('down'));
    const { result } = await renderHook(() => useLoader(fetcher, QUIET));
    await flush();
    expect(result.current).toMatchObject({ data: null, loading: false, failing: true });
  });

  it('retries after 3s, 6s and 12s, then every 30s, until it succeeds', async () => {
    const fetcher = jest.fn().mockRejectedValue(new Error('down'));
    const { result } = await renderHook(() => useLoader(fetcher, QUIET));
    await flush();
    expect(fetcher).toHaveBeenCalledTimes(1);

    const gaps = [3_000, 6_000, 12_000, 30_000, 30_000];
    let calls = 1;
    for (const gap of gaps) {
      await advance(gap - 1);
      expect(fetcher).toHaveBeenCalledTimes(calls);
      await advance(1);
      calls += 1;
      expect(fetcher).toHaveBeenCalledTimes(calls);
    }

    fetcher.mockResolvedValue('ok');
    await advance(30_000);
    expect(result.current).toMatchObject({ data: 'ok', failing: false });
    const settled = fetcher.mock.calls.length;
    await advance(120_000);
    expect(fetcher).toHaveBeenCalledTimes(settled);
  });

  it('does not retry an answer that asking again will not change', async () => {
    const fetcher = jest.fn().mockRejectedValue(new ApiError(404, 'not_found'));
    const { result } = await renderHook(() => useLoader(fetcher, QUIET));
    await flush();
    expect(result.current).toMatchObject({ failing: true, retrying: false });
    await advance(120_000);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it.each([
    [new Error('offline'), true],
    [new ApiError(500, 'x'), true],
    [new ApiError(503, 'x'), true],
    [new ApiError(408, 'x'), true],
    [new ApiError(429, 'x'), true],
    [new ApiError(404, 'x'), false],
    [new ApiError(401, 'x'), false],
    [new ApiError(400, 'x'), false],
  ])('isRetryable(%s) is %s', (error, expected) => {
    expect(isRetryable(error)).toBe(expected);
  });

  it('stops retrying when the screen goes away', async () => {
    const fetcher = jest.fn().mockRejectedValue(new Error('down'));
    const { unmount } = await renderHook(() => useLoader(fetcher, QUIET));
    await flush();
    await unmount();
    await advance(120_000);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('reloads when its tab is pressed', async () => {
    const fetcher = jest.fn().mockResolvedValueOnce('a').mockResolvedValueOnce('b');
    const { result, unmount } = await renderHook(() => useLoader(fetcher, QUIET));
    await flush();
    expect(result.current.data).toBe('a');
    expect(mockTabPressed.size).toBe(1);

    await act(async () => {
      mockTabPressed.forEach((listener) => listener());
    });
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(result.current.data).toBe('b');

    await unmount();
    expect(mockTabPressed.size).toBe(0);
  });

  it('ignores an answer that arrives after a newer one', async () => {
    const answers: ((value: string) => void)[] = [];
    const fetcher = jest.fn(() => new Promise<string>((resolve) => answers.push(resolve)));
    const { result } = await renderHook(() => useLoader(fetcher, QUIET));
    await act(async () => {
      void result.current.reload();
    });
    expect(answers).toHaveLength(2);

    await act(async () => {
      answers[1]('new');
    });
    await act(async () => {
      answers[0]('old');
    });
    expect(result.current.data).toBe('new');
  });

  it('reloads when given a different fetcher and shows the old data until it lands', async () => {
    const first = jest.fn().mockResolvedValue('one');
    const second = jest.fn().mockResolvedValue('two');
    const { result, rerender } = await renderHook(
      ({ fetcher }: { fetcher: () => Promise<string> }) => useLoader(fetcher, QUIET),
      { initialProps: { fetcher: first } },
    );
    await flush();
    expect(result.current.data).toBe('one');
    await rerender({ fetcher: second });
    await flush();
    expect(second).toHaveBeenCalledTimes(1);
    expect(result.current.data).toBe('two');
  });
});
