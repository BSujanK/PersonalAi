import { requireNativeModule } from 'expo';
import { Platform } from 'react-native';

export interface QueuedSms {
  id: string;
  sender: string;
  body: string;
  received_at: number; // epoch milliseconds
}

interface BankSmsModule {
  /** Replace the sender allowlist (normalised IDs). Senders starting with "BOB" always pass. */
  setAllowedSenders(senders: string[]): void;
  /** Queue bank SMS from the inbox received after `sinceMs`; resolves to the number added. */
  scanInbox(sinceMs: number): Promise<number>;
  peekQueue(limit: number): Promise<QueuedSms[]>;
  removeFromQueue(ids: string[]): Promise<void>;
  queueSize(): Promise<number>;
  /** Fire ACTION_SET_ALARM (days: 1 = Sunday ... 7 = Saturday). Needs the app in the foreground. */
  setAlarm(hour: number, minute: number, label: string, days: number[] | null): Promise<void>;
  /** Fire ACTION_SET_TIMER. Needs the app in the foreground. */
  setTimer(seconds: number, label: string): Promise<void>;
  /** Whether the owner has switched on this app's payment-notification listener in Android. */
  notificationAccessEnabled(): boolean;
  /** Open Android's notification access screen; the listener can only be enabled there. */
  openNotificationAccessSettings(): void;
}

const BankSms = requireNativeModule<BankSmsModule>('BankSms');

/** False off Android, where the notification listener does not exist. */
export const notificationAccessEnabled = (): boolean =>
  Platform.OS === 'android' && BankSms.notificationAccessEnabled();

/** A no-op off Android. */
export const openNotificationAccessSettings = (): void => {
  if (Platform.OS === 'android') BankSms.openNotificationAccessSettings();
};

export default BankSms;
