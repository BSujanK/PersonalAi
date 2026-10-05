// Glue between the native bank-sms module, the server and local settings.
import { PermissionsAndroid, Platform } from 'react-native';

import BankSms from '../../modules/bank-sms';
import { getSmsSenders, postSms } from './api';
import { getJson, setJson } from './prefs';
import { sanitiseSenders } from './senders';
import { flushQueue, type FlushResult } from './smsSync';

const CUSTOM_KEY = 'sms.custom_senders';
const DEFAULTS_KEY = 'sms.default_senders';
const DAY_MS = 86_400_000;

export const getCustomSenders = () => getJson<string[]>(CUSTOM_KEY, []);
export const getDefaultSenders = () => getJson<string[]>(DEFAULTS_KEY, []);

export async function saveCustomSenders(senders: string[]): Promise<void> {
  await setJson(CUSTOM_KEY, sanitiseSenders(senders));
  await applyAllowlist();
}

/** Push defaults (cached from the server) plus custom IDs to the native receiver. */
export async function applyAllowlist(): Promise<void> {
  const [defaults, custom] = await Promise.all([getDefaultSenders(), getCustomSenders()]);
  BankSms.setAllowedSenders(sanitiseSenders([...defaults, ...custom]));
}

/** Refresh the server's default sender list when reachable; the cached copy is used otherwise. */
export async function refreshDefaultSenders(): Promise<string[]> {
  try {
    const { senders } = await getSmsSenders();
    await setJson(DEFAULTS_KEY, sanitiseSenders(senders));
  } catch {
    // Offline or older server: keep the cached list.
  }
  await applyAllowlist();
  return getDefaultSenders();
}

export async function hasSmsPermission(): Promise<boolean> {
  if (Platform.OS !== 'android') return false;
  const [read, receive] = await Promise.all([
    PermissionsAndroid.check(PermissionsAndroid.PERMISSIONS.READ_SMS),
    PermissionsAndroid.check(PermissionsAndroid.PERMISSIONS.RECEIVE_SMS),
  ]);
  return read && receive;
}

export async function requestSmsPermission(): Promise<boolean> {
  if (Platform.OS !== 'android') return false;
  const result = await PermissionsAndroid.requestMultiple([
    PermissionsAndroid.PERMISSIONS.READ_SMS,
    PermissionsAndroid.PERMISSIONS.RECEIVE_SMS,
  ]);
  return Object.values(result).every((r) => r === PermissionsAndroid.RESULTS.GRANTED);
}

export const flushSmsQueue = (): Promise<FlushResult> =>
  flushQueue({
    peek: (limit) => BankSms.peekQueue(limit),
    remove: (ids) => BankSms.removeFromQueue(ids),
    post: postSms,
  });

/** Queue bank SMS from the last `days` days, then upload. Returns how many were queued. */
export async function importRecent(days: number): Promise<number> {
  await applyAllowlist();
  const added = await BankSms.scanInbox(Date.now() - days * DAY_MS);
  await flushSmsQueue();
  return added;
}

export const smsQueueSize = () => BankSms.queueSize();
