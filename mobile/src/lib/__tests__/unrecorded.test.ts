import {
  formatWindow,
  inferredSubtitle,
  inferredTitle,
  isInferred,
  mismatchLine,
} from '../unrecorded';

const at = (day: number, hour: number, minute: number) =>
  new Date(2026, 9, day, hour, minute).toISOString();
const clock = (iso: string) =>
  new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
const dayOf = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });

describe('isInferred', () => {
  it('accepts the inferred flag or the unrecorded category', () => {
    expect(isInferred({ inferred: true, category: null })).toBe(true);
    expect(isInferred({ category: 'unrecorded' })).toBe(true);
  });

  it('rejects a normal row and an older server that sends neither field', () => {
    expect(isInferred({ inferred: false, category: 'food' })).toBe(false);
    expect(isInferred({ category: null })).toBe(false);
  });
});

describe('inferredTitle', () => {
  it('names a debit a payment and a credit money in', () => {
    expect(inferredTitle({ direction: 'debit' })).toBe('Unrecorded payment');
    expect(inferredTitle({ direction: 'credit' })).toBe('Unrecorded money in');
  });
});

describe('formatWindow', () => {
  it('shows only the two times when both fall on one local day', () => {
    const from = at(7, 9, 48);
    const to = at(7, 15, 42);
    expect(formatWindow(from, to)).toBe(`${clock(from)} and ${clock(to)}`);
  });

  it('adds the date to each end when the window spans days', () => {
    const from = at(7, 21, 5);
    const to = at(8, 8, 30);
    expect(formatWindow(from, to)).toBe(
      `${dayOf(from)}, ${clock(from)} and ${dayOf(to)}, ${clock(to)}`,
    );
  });

  it('shows unparseable input as received instead of throwing', () => {
    expect(formatWindow('soon', 'later')).toBe('soon and later');
  });
});

describe('inferredSubtitle', () => {
  it('says there was no bank SMS and when the balance changed', () => {
    const window = { from: at(7, 9, 48), to: at(7, 15, 42) };
    expect(inferredSubtitle({ window, date: '2026-10-07' })).toBe(
      `No bank SMS · balance changed between ${formatWindow(window.from, window.to)}`,
    );
  });

  it('falls back to the date when the server sent no window', () => {
    expect(inferredSubtitle({ window: null, date: '2026-10-07' })).toBe(
      '2026-10-07 · No bank SMS · balance changed',
    );
    expect(inferredSubtitle({ date: '2026-10-07' })).toContain('2026-10-07');
  });
});

describe('mismatchLine', () => {
  it('states the shortfall with Indian grouping and the window', () => {
    const m = {
      account: 'XX1234',
      from: at(7, 9, 48),
      to: at(7, 15, 42),
      amount_inr: '12500.50',
      direction: 'debit' as const,
    };
    expect(mismatchLine(m)).toBe(
      `Balance doesn't add up by ₹12,500.50 between ${formatWindow(m.from, m.to)}`,
    );
  });
});
