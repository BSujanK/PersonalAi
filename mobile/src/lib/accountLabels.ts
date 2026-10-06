// Friendly labels for the owner's mail accounts ("College", or the address itself), from the
// agent's GET /accounts. Labels come from the laptop's configuration; none are hard-coded here.
import { useEffect, useState } from 'react';

import { getAccounts } from './api';

type Labels = Record<string, string>;

let cached: Promise<Labels> | null = null;

function load(): Promise<Labels> {
  if (!cached) {
    cached = getAccounts().then(
      ({ accounts }) =>
        Object.fromEntries(accounts.map((a) => [a.account.toLowerCase(), a.label])) as Labels,
      () => {
        cached = null; // an older agent or offline: retry on the next screen
        return {};
      },
    );
  }
  return cached;
}

/** Test hook: forget the cached labels. */
export function resetAccountLabelsForTests(): void {
  cached = null;
}

/** The label for an account; the account itself until labels load or when none is set. */
export function labelFor(labels: Labels, account: string): string {
  return labels[account.toLowerCase()] ?? account;
}

export function useAccountLabels(): (account: string) => string {
  const [labels, setLabels] = useState<Labels>({});
  useEffect(() => {
    let live = true;
    void load().then((loaded) => {
      if (live) setLabels(loaded);
    });
    return () => {
      live = false;
    };
  }, []);
  return (account: string) => labelFor(labels, account);
}
