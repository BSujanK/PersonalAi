// A content-free local notice when an action starts waiting for approval while the app is in the
// background (CLAUDE.md rule 7). The text is only a count: no title, recipient or message text
// ever goes into it. Tapping it opens the Approvals tab, where the details are fetched over
// Tailscale as usual.
import * as Notifications from 'expo-notifications';
import { AppState, Platform } from 'react-native';

import { listApprovals } from './api';
import { ALERT_CHANNEL, alertsPermitted, prepareChannel, type AlertData } from './alerts';
import { loadSeenApprovals, rememberApprovals, unseenApprovals } from './approvalSeen';

/** The notification text for `count` newly waiting actions: a number and nothing else. */
export function approvalNoticeBody(count: number): string {
  return count === 1 ? '1 action waiting for approval' : `${count} actions waiting for approval`;
}

/**
 * Announce actions that began waiting while the app was away. Does nothing in the foreground
 * (the Approvals badge and the chat already show them) or without notification permission. The
 * first run only records what is waiting, like the alert feed does, so nothing old is replayed.
 */
export async function notifyNewApprovals(): Promise<void> {
  if (AppState.currentState === 'active') return;
  const pending = (await listApprovals()).map((item) => item.id);
  const seen = await loadSeenApprovals();
  await rememberApprovals(pending);
  if (seen === null) return;
  const fresh = unseenApprovals(pending, seen);
  if (fresh.length === 0 || !(await alertsPermitted())) return;
  await prepareChannel();
  const data: AlertData = { alertId: 0, target: { type: 'approvals' } };
  await Notifications.scheduleNotificationAsync({
    content: {
      title: 'PersonalAi',
      body: approvalNoticeBody(fresh.length),
      data,
      ...(Platform.OS === 'android' ? { channelId: ALERT_CHANNEL } : {}),
    },
    trigger: null,
  });
}
