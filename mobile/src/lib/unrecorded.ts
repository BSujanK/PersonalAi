// Wording for payments the bank sent no SMS for. The agent infers them from a balance that moved
// between two readings; they are shown quietly and are never presented as a confirmed payment.
import type { Txn } from './api';

export function isInferred(txn: Pick<Txn, 'inferred' | 'category'>): boolean {
  return txn.inferred === true || txn.category === 'unrecorded';
}

export function inferredTitle(txn: Pick<Txn, 'direction'>): string {
  return txn.direction === 'credit' ? 'Unrecorded money in' : 'Unrecorded payment';
}

function parse(iso: string): Date | null {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date;
}

function sameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

const TIME = { hour: 'numeric', minute: '2-digit' } as const;
const DAY = { day: 'numeric', month: 'short' } as const;

/**
 * "9:48 am and 3:42 pm" in local time; each end carries its date ("7 Oct, 9:48 am and 8 Oct,
 * 3:42 pm") when the window spans days. Unparseable input is shown as received.
 */
export function formatWindow(from: string, to: string): string {
  const start = parse(from);
  const end = parse(to);
  if (!start || !end) return `${from} and ${to}`;
  const clock = (d: Date) => d.toLocaleTimeString(undefined, TIME);
  if (sameDay(start, end)) return `${clock(start)} and ${clock(end)}`;
  const stamp = (d: Date) => `${d.toLocaleDateString(undefined, DAY)}, ${clock(d)}`;
  return `${stamp(start)} and ${stamp(end)}`;
}

/** "No bank SMS · balance changed between 9:48 am and 3:42 pm". */
export function inferredSubtitle(txn: Pick<Txn, 'window' | 'date'>): string {
  const { window } = txn;
  return window
    ? `No bank SMS · balance changed between ${formatWindow(window.from, window.to)}`
    : `${txn.date} · No bank SMS · balance changed`;
}
