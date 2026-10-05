import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

import { loadPairing, type StoredPairing } from './secureKeys';

interface PairingState {
  /** undefined while loading, null when not paired. */
  pairing: StoredPairing | null | undefined;
  reload: () => Promise<void>;
}

const PairingContext = createContext<PairingState>({
  pairing: undefined,
  reload: async () => {},
});

export function PairingProvider({ children }: { children: ReactNode }) {
  const [pairing, setPairing] = useState<StoredPairing | null | undefined>(undefined);

  const reload = useCallback(async () => {
    try {
      setPairing(await loadPairing());
    } catch {
      setPairing(null);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    loadPairing().then(
      (stored) => !cancelled && setPairing(stored),
      () => !cancelled && setPairing(null),
    );
    return () => {
      cancelled = true;
    };
  }, []);

  const value = useMemo(() => ({ pairing, reload }), [pairing, reload]);
  return <PairingContext.Provider value={value}>{children}</PairingContext.Provider>;
}

export const usePairing = () => useContext(PairingContext);
