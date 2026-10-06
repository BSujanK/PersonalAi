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

export function shortDateTime(iso: string | undefined | null): string {
  if (!iso) return '';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

/** "1.2 MB", "340 KB" or "12 B". */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
