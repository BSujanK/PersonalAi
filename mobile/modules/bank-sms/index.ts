import { requireNativeModule } from 'expo';

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
}

export default requireNativeModule<BankSmsModule>('BankSms');
