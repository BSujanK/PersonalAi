// Alerts are LOCAL notifications built from the agent's /notifications feed, fetched over
// Tailscale. Nothing with content goes through Expo push (CLAUDE.md rule 7).
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

import {
  getAlertSettings,
  getNotifications,
  undoAutoEvent,
  type AlertItem,
  type AlertKind,
  type AlertSettings,
  type AlertTarget,
} from './api';
import { getJson, setJson } from './prefs';
import { emitRefresh } from './refreshBus';

export const ALERT_CHANNEL = 'alerts';
export const UNDO_CATEGORY = 'calendar_added';
export const UNDO_ACTION = 'undo';
const LAST_ID_KEY = 'alerts.lastId';

/** Which setting switches an alert kind. Auto-added calendar events have no switch of their own. */
const KIND_SETTING: Record<
  AlertKind,
  keyof Pick<AlertSettings, 'important_mail' | 'deadlines' | 'briefing'> | null
> = {
  important_mail: 'important_mail',
  deadline: 'deadlines',
  briefing: 'briefing',
  calendar_added: null,
};

/** Items newer than `lastId`, oldest first. */
export function newerThan(items: readonly AlertItem[], lastId: number): AlertItem[] {
  return items.filter((item) => item.id > lastId).sort((a, b) => a.id - b.id);
}

export function isKindEnabled(kind: AlertKind, settings: AlertSettings): boolean {
  const key = KIND_SETTING[kind];
  return key === null ? true : settings[key];
}

export type AlertRoute =
  | { pathname: '/mail/[account]/[id]'; params: { account: string; id: string } }
  | { pathname: '/deadline/[id]'; params: { id: string } }
  | { pathname: '/today' | '/inbox' | '/approvals' };

const mailRoute = (account: string, id: string): AlertRoute => ({
  pathname: '/mail/[account]/[id]',
  params: { account, id },
});

const deadlineRoute = (id: number): AlertRoute => ({
  pathname: '/deadline/[id]',
  params: { id: String(id) },
});

/**
 * Where tapping an alert goes: a mail opens that message; a deadline found in mail opens the mail
 * it came from; an auto-added calendar event, and any other deadline, opens the deadline (which
 * shows the event and its source); "more important mail" opens the inbox; everything else (a
 * briefing, an alert from an older agent without a target) opens Today. `kind` is the alert's
 * kind, when known.
 */
export function routeForTarget(
  target: AlertTarget | null | undefined,
  kind?: AlertKind,
): AlertRoute {
  switch (target?.type) {
    case 'mail': {
      const id = target.id ?? target.message_id;
      return id ? mailRoute(target.account, id) : { pathname: '/today' };
    }
    case 'deadline':
      if (kind === 'calendar_added') return deadlineRoute(target.deadline_id);
      return target.source === 'mail' && target.account && target.message_id
        ? mailRoute(target.account, target.message_id)
        : deadlineRoute(target.deadline_id);
    case 'inbox':
      return { pathname: '/inbox' };
    case 'approvals':
      return { pathname: '/approvals' };
    default:
      return { pathname: '/today' };
  }
}

/** The account an alert came from, if the agent said so. */
export function alertAccount(item: AlertItem): string | null {
  if (item.source_account) return item.source_account;
  const t = item.target;
  if (t.type === 'mail') return t.account;
  if (t.type === 'deadline' || t.type === 'inbox') return t.account ?? null;
  return null;
}

export interface AlertData extends Record<string, unknown> {
  alertId: number;
  /** Absent in notifications shown by an older build. */
  kind?: AlertKind;
  target: AlertTarget;
  deadlineId?: number;
}

export interface AlertContent {
  title: string;
  body: string;
  data: AlertData;
  categoryIdentifier?: string;
}

export function toContent(item: AlertItem): AlertContent {
  const data: AlertData = { alertId: item.id, kind: item.kind, target: item.target };
  if (item.target.type === 'deadline') data.deadlineId = item.target.deadline_id;
  const undoable = item.kind === 'calendar_added' && (item.actions ?? []).includes(UNDO_ACTION);
  return {
    title: item.title,
    body: item.body,
    data,
    ...(undoable && data.deadlineId !== undefined ? { categoryIdentifier: UNDO_CATEGORY } : {}),
  };
}

export type ResponseOutcome =
  | { type: 'undo'; deadlineId: number }
  | { type: 'route'; route: AlertRoute };

/** What a tap on a notification, or on its action button, should do. */
export function outcomeForResponse(actionIdentifier: string, data: unknown): ResponseOutcome {
  const record = (data ?? {}) as Partial<AlertData>;
  if (actionIdentifier === UNDO_ACTION) {
    const id = record.deadlineId;
    if (typeof id === 'number' && Number.isInteger(id)) return { type: 'undo', deadlineId: id };
  }
  return { type: 'route', route: routeForTarget(record.target, record.kind) };
}

export async function alertsPermitted(): Promise<boolean> {
  const { status } = await Notifications.getPermissionsAsync();
  return status === 'granted';
}

/** Ask for notification permission (Android 13+ shows the system prompt). */
export async function requestAlertPermission(): Promise<boolean> {
  if (await alertsPermitted()) return true;
  const { status } = await Notifications.requestPermissionsAsync();
  return status === 'granted';
}

export async function prepareChannel(): Promise<void> {
  if (Platform.OS === 'android') {
    await Notifications.setNotificationChannelAsync(ALERT_CHANNEL, {
      name: 'Alerts',
      importance: Notifications.AndroidImportance.HIGH,
    });
  }
  await Notifications.setNotificationCategoryAsync(UNDO_CATEGORY, [
    // Opens the app so the JS listener runs even when the app was killed; undo is idempotent on
    // the server, so handling the same response twice is harmless.
    { identifier: UNDO_ACTION, buttonTitle: 'Undo', options: { opensAppToForeground: true } },
  ]);
}

async function show(content: AlertContent): Promise<void> {
  await Notifications.scheduleNotificationAsync({
    content: {
      title: content.title,
      body: content.body,
      data: content.data,
      ...(content.categoryIdentifier ? { categoryIdentifier: content.categoryIdentifier } : {}),
      ...(Platform.OS === 'android' ? { channelId: ALERT_CHANNEL } : {}),
    },
    trigger: null,
  });
}

let running: Promise<void> | null = null;

async function run(): Promise<void> {
  const lastId = await getJson<number | null>(LAST_ID_KEY, null);
  const feed = await getNotifications(lastId ?? 0);
  if (lastId === null) {
    // First run: remember where the feed is, so history is not replayed as a flood.
    await setJson(LAST_ID_KEY, feed.latest_id);
    return;
  }
  const fresh = newerThan(feed.items, lastId);
  if (fresh.length === 0) return;
  // Without permission the alerts are skipped, not queued: granting it later must not replay them.
  const permitted = await alertsPermitted();
  const settings = permitted ? await getAlertSettings() : null;
  if (permitted) await prepareChannel();
  for (const item of fresh) {
    if (settings && isKindEnabled(item.kind, settings)) await show(toContent(item));
    await setJson(LAST_ID_KEY, item.id);
  }
}

/**
 * Show alerts that arrived since the last check. Safe to call from the foreground and from the
 * background task: concurrent calls share one run, and errors are left for the caller to ignore
 * (the id advances per alert after it was shown, so the rest are retried next time).
 */
export function checkAlerts(): Promise<void> {
  running ??= run().finally(() => {
    running = null;
  });
  return running;
}

/** Handle a tap on an alert or its Undo button. `navigate` is the router's push. */
export async function handleAlertResponse(
  response: Notifications.NotificationResponse,
  navigate: (route: AlertRoute) => void,
): Promise<void> {
  const outcome = outcomeForResponse(
    response.actionIdentifier,
    response.notification.request.content.data,
  );
  if (outcome.type === 'undo') {
    try {
      await undoAutoEvent(outcome.deadlineId);
    } finally {
      emitRefresh();
    }
    return;
  }
  navigate(outcome.route);
}
