import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { AppState } from 'react-native';

import { health, listApprovals } from './api';
import { rememberApprovals } from './approvalSeen';
import { onRefresh } from './refreshBus';

const POLL_MS = 20_000;

interface AgentStatus {
  /** null until the first check finishes. */
  online: boolean | null;
  pendingCount: number;
  /** Check again now (after a failed send, say). */
  refresh: () => void;
}

const StatusContext = createContext<AgentStatus>({
  online: null,
  pendingCount: 0,
  refresh: () => undefined,
});

/** Polls /health and the approval count for the drawer badge and the composer's offline state. */
export function AgentStatusProvider({ children }: { children: ReactNode }) {
  const [online, setOnline] = useState<boolean | null>(null);
  const [pendingCount, setPendingCount] = useState(0);
  const mounted = useRef(true);

  const refresh = useCallback(() => {
    health().then(
      () => {
        if (!mounted.current) return;
        setOnline(true);
        listApprovals().then(
          (items) => {
            if (!mounted.current) return;
            setPendingCount(items.length);
            // Seen in the app, so the background check will not announce them again.
            if (AppState.currentState === 'active') {
              void rememberApprovals(items.map((item) => item.id)).catch(() => undefined);
            }
          },
          () => undefined,
        );
      },
      () => mounted.current && setOnline(false),
    );
  }, []);

  useEffect(() => {
    mounted.current = true;
    refresh();
    const timer = setInterval(() => {
      if (AppState.currentState === 'active') refresh();
    }, POLL_MS);
    const sub = AppState.addEventListener('change', (state) => {
      if (state === 'active') refresh();
    });
    const unsubscribe = onRefresh(refresh);
    return () => {
      mounted.current = false;
      clearInterval(timer);
      sub.remove();
      unsubscribe();
    };
  }, [refresh]);

  const value = useMemo(() => ({ online, pendingCount, refresh }), [online, pendingCount, refresh]);
  return <StatusContext.Provider value={value}>{children}</StatusContext.Provider>;
}

export const useAgentStatus = () => useContext(StatusContext);
