// Whether the owner has switched on the payment-notification listener (Android's "notification
// access"). Only PhonePe, GPay and bob World notifications are read, and the allowlist is fixed
// in the native module. The setting lives in Android, so it is re-read on focus and on foreground.
import { useCallback, useState } from 'react';

import { notificationAccessEnabled, openNotificationAccessSettings } from '../../modules/bank-sms';
import { usePolling } from './usePolling';

/** The native answer, or false when it cannot be read (off Android, or the module is missing). */
export function readNotificationAccess(read: () => boolean = notificationAccessEnabled): boolean {
  try {
    return read();
  } catch {
    return false;
  }
}

export { openNotificationAccessSettings };

/** `null` until the first check; re-checked whenever the screen gains focus or the app resumes. */
export function useNotificationAccess(): boolean | null {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const check = useCallback(() => setEnabled(readNotificationAccess()), []);
  usePolling(check);
  return enabled;
}
