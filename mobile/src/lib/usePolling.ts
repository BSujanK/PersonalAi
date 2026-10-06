import { useFocusEffect, useNavigation } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';

import { ApiError } from './api';
import { onRefresh } from './refreshBus';

export const POLL_MS = 30_000;
/** Waits before each retry after a failed load; the last one repeats. */
const RETRY_MS = [3_000, 6_000, 12_000, 30_000] as const;

/** The slice of a screen's navigation object used here. Only tab navigators emit `tabPress`. */
interface TabPressSource {
  addListener(type: 'tabPress', listener: () => void): () => void;
}

/**
 * Run `load` when the screen gains focus, every 30s while focused, when its tab is pressed, when
 * the app returns to the foreground and on any refresh signal.
 */
export function usePolling(load: () => void | Promise<void>, intervalMs: number = POLL_MS): void {
  const latest = useRef(load);
  useEffect(() => {
    latest.current = load;
  });
  const navigation = useNavigation<TabPressSource>();

  useFocusEffect(
    useCallback(() => {
      const run = () => {
        void latest.current();
      };
      run();
      const timer = setInterval(() => {
        if (AppState.currentState === 'active') run();
      }, intervalMs);
      const unsubscribe = onRefresh(run);
      // Pressing the tab of the screen already open reloads it; pressing another tab focuses it,
      // which loads above.
      const unsubscribeTab = navigation.addListener('tabPress', run);
      return () => {
        clearInterval(timer);
        unsubscribe();
        unsubscribeTab();
      };
    }, [intervalMs, navigation]),
  );

  useEffect(() => {
    const sub = AppState.addEventListener('change', (state) => {
      if (state === 'active') void latest.current();
    });
    return () => sub.remove();
  }, []);
}

export interface Loader<T> {
  /** The last successful result; kept when a later refresh fails. */
  data: T | null;
  /** Why the last attempt failed; null after a success. */
  error: unknown;
  /** No data yet and nothing has failed: the first request is in flight or about to start. */
  loading: boolean;
  /** The last attempt failed. Retries run on their own while the screen is focused. */
  failing: boolean;
  /** A retry is scheduled: false for answers that will not change by asking again (a 404). */
  retrying: boolean;
  reload: () => Promise<void>;
}

/**
 * Load `fetcher` with usePolling and keep the last good result. A refresh that fails leaves
 * `data` in place and flags `failing`; the screen then retries after 3s, 6s, 12s and every 30s
 * after that, until it succeeds or loses focus. Answers that arrive out of order are dropped.
 * `fetcher` must be stable (module level or useCallback): a new one reloads, keeping the old
 * data on screen until the new answer lands.
 */
/**
 * Whether asking again can help: network failures, timeouts and server errors can; a client error
 * (not found, unauthorised, bad request) will answer the same until something else changes.
 */
export function isRetryable(error: unknown): boolean {
  if (!(error instanceof ApiError)) return true;
  return error.status >= 500 || error.status === 408 || error.status === 429;
}

export function useLoader<T>(
  fetcher: () => Promise<T>,
  { intervalMs = POLL_MS }: { intervalMs?: number } = {},
): Loader<T> {
  const [state, setState] = useState<{ data: T | null; error: unknown; failures: number }>({
    data: null,
    error: null,
    failures: 0,
  });
  const latest = useRef(fetcher);
  const started = useRef(0);
  const applied = useRef(0);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const reload = useCallback(async () => {
    const mine = ++started.current;
    let outcome: { data: T } | { error: unknown };
    try {
      outcome = { data: await latest.current() };
    } catch (error) {
      outcome = { error };
    }
    // A newer request already answered, or the screen is gone.
    if (!mounted.current || mine < applied.current) return;
    applied.current = mine;
    setState((prev) =>
      'data' in outcome
        ? { data: outcome.data, error: null, failures: 0 }
        : { data: prev.data, error: outcome.error, failures: prev.failures + 1 },
    );
  }, []);

  useEffect(() => {
    latest.current = fetcher;
  });
  usePolling(reload, intervalMs);

  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    void reload();
  }, [fetcher, reload]);

  const { failures } = state;
  const retrying = failures > 0 && isRetryable(state.error);
  useFocusEffect(
    useCallback(() => {
      if (!retrying) return;
      const wait = RETRY_MS[Math.min(failures, RETRY_MS.length) - 1];
      const timer = setTimeout(() => void reload(), wait);
      return () => clearTimeout(timer);
    }, [failures, retrying, reload]),
  );

  return {
    data: state.data,
    error: state.error,
    loading: state.data === null && failures === 0,
    failing: failures > 0,
    retrying,
    reload,
  };
}

/** Props for Screen's pull-to-refresh gesture: shows the spinner while `reload` runs. */
export function usePullToRefresh(reload: () => Promise<void>): {
  refreshing: boolean;
  onRefresh: () => void;
} {
  const [refreshing, setRefreshing] = useState(false);
  const onRefresh = useCallback(() => {
    setRefreshing(true);
    void reload().finally(() => setRefreshing(false));
  }, [reload]);
  return { refreshing, onRefresh };
}
