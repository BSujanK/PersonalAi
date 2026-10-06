// The figure at the top of Chat's empty state: today's spend against yesterday's, falling back to
// the total balance. Only aggregates are fetched; no transaction rows.
import { getBalances, getSummary } from './api';
import { formatInr } from './format';

/** The small line under the figure. `good` picks green over red; flat lines stay muted. */
export type Delta = { text: string; direction: 'up' | 'down' | 'flat'; good?: boolean };

export interface SpendHero {
  label: string;
  /** Whole rupees. */
  amount: number;
  delta: Delta | null;
}

/** Today's spend against yesterday's; falls back to the total balance, then to null. */
export async function loadSpendHero(): Promise<SpendHero | null> {
  try {
    const [today, yesterday] = await Promise.all([getSummary('today'), getSummary('yesterday')]);
    const spent = Math.round(Number(today.spent_inr) || 0);
    const before = Math.round(Number(yesterday.spent_inr) || 0);
    const diff = spent - before;
    const delta: Delta =
      diff === 0
        ? { text: 'Same as yesterday', direction: 'flat' }
        : {
            text: `${formatInr(String(Math.abs(diff)))} ${diff > 0 ? 'more' : 'less'} than yesterday`,
            direction: diff > 0 ? 'up' : 'down',
            // Spending less than yesterday is the good news.
            good: diff < 0,
          };
    return { label: 'Spent today', amount: spent, delta };
  } catch {
    try {
      const { accounts } = await getBalances();
      if (accounts.length === 0) return null;
      const total = accounts.reduce((sum, a) => sum + (Number(a.balance_inr) || 0), 0);
      return {
        label: 'Total balance',
        amount: Math.round(total),
        delta: {
          text: `Across ${accounts.length} account${accounts.length === 1 ? '' : 's'}`,
          direction: 'flat',
        },
      };
    } catch {
      return null;
    }
  }
}
