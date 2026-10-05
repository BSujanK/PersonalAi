import { useFocusEffect } from 'expo-router';
import { useCallback, useEffect, useRef } from 'react';
import { AppState } from 'react-native';

import { onRefresh } from './refreshBus';

export const POLL_MS = 30_000;

/** Run `load` when the screen gains focus, every 30s while focused, and on any refresh signal. */
export function usePolling(load: () => void | Promise<void>, intervalMs: number = POLL_MS): void {
  const latest = useRef(load);
  useEffect(() => {
    latest.current = load;
  });

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
      return () => {
        clearInterval(timer);
        unsubscribe();
      };
    }, [intervalMs]),
  );

  useEffect(() => {
    const sub = AppState.addEventListener('change', (state) => {
      if (state === 'active') void latest.current();
    });
    return () => sub.remove();
  }, []);
}
