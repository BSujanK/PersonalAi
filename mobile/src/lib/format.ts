import { ApiError, OfflineError } from './api';
import { BiometricUnavailableError } from './secureKeys';

export function errorMessage(error: unknown): string {
  if (error instanceof OfflineError)
    return 'Agent offline. Check that the laptop is on and Tailscale is connected.';
  if (error instanceof BiometricUnavailableError) {
    return 'Pairing needs a fingerprint or face unlock enrolled on this phone. Set one up in Android settings, then try again.';
  }
  if (error instanceof ApiError) {
    if (error.status === 401) return 'The agent rejected this device. Unpair and pair again.';
    if (error.status === 404) return 'Not available on the agent (not configured).';
    if (error.status === 503) return 'The language model is unavailable right now.';
    return `The agent refused the request (${error.status}: ${error.detail}).`;
  }
  return error instanceof Error ? error.message : 'Something went wrong.';
}

/** "12 min left", "45 s left" or "expired". */
export function timeLeft(expiresAt: string, now: number = Date.now()): string {
  const ms = Date.parse(expiresAt) - now;
  if (Number.isNaN(ms) || ms <= 0) return 'expired';
  const seconds = Math.floor(ms / 1000);
  return seconds >= 60 ? `${Math.floor(seconds / 60)} min left` : `${seconds} s left`;
}

/** True when fewer than `ms` milliseconds remain (or the time has passed). */
export function expiresWithin(expiresAt: string, ms: number, now: number = Date.now()): boolean {
  return Date.parse(expiresAt) - now < ms;
}

export function shortDateTime(iso: string | undefined | null): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  // "Wed, 7 Oct, 12:36": no seconds, no year; the weekday helps more than the date for plans.
  return date.toLocaleString(undefined, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

/** A deadline's due: an all-day date shows without a time, a datetime like `shortDateTime`. */
export function dueLabel(due: string | undefined | null): string {
  const match = due ? DATE_ONLY.exec(due) : null;
  if (!match) return shortDateTime(due);
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return date.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });
}

/** "Friday, 9 October 2026" for a date-only due, with ", 17:00" when it has a time. */
export function fullDateTime(iso: string | undefined | null): string {
  if (!iso) return '';
  const match = DATE_ONLY.exec(iso);
  const date = match
    ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
    : new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const day = { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' } as const;
  return match
    ? date.toLocaleDateString(undefined, day)
    : date.toLocaleString(undefined, { ...day, hour: '2-digit', minute: '2-digit' });
}

/** "1.2 MB", "340 KB" or "12 B". */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function sameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

/** "09:30" today, "Yesterday", or "5 Oct" for a list row's trailing time. */
export function rowTime(iso: string | undefined | null, now: Date = new Date()): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  if (sameDay(date, now)) {
    return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  }
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (sameDay(date, yesterday)) return 'Yesterday';
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}

/** "Tuesday, 6 October" for a screen subtitle. */
export function longDate(now: Date = new Date()): string {
  return now.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' });
}

/** Initials for an avatar: "Asha Rao" -> "AR", "asha@example.com" -> "A". */
export function initials(name: string): string {
  const words = name
    .replace(/@.*$/, '')
    .split(/[\s._-]+/)
    .filter(Boolean);
  const letters = words.length > 1 ? [words[0], words[words.length - 1]] : words.slice(0, 1);
  return letters.map((w) => w.charAt(0).toUpperCase()).join('') || '?';
}

/** "₹1,23,456.50" from the agent's decimal string, with Indian digit grouping. */
export function formatInr(amount: string | number): string {
  const text = String(amount).trim();
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(text);
  if (!match) return `₹${text}`;
  const [, sign, whole, frac] = match;
  const last3 = whole.slice(-3);
  const rest = whole.slice(0, -3);
  const grouped = rest ? `${rest.replace(/\B(?=(\d{2})+(?!\d))/g, ',')},${last3}` : last3;
  const paise = frac ? `.${frac.padEnd(2, '0').slice(0, 2)}` : '';
  return `${sign}₹${grouped}${paise}`;
}

/** "this_month" -> "This month". */
export function periodLabel(period: string): string {
  const words = period.replace(/_/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}
