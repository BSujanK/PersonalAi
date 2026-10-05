// Push is optional. Notifications carry no content (CLAUDE.md rule 7): receiving one only
// triggers a refresh. Without an EAS project id the app silently relies on 30s foreground polling.
import Constants from 'expo-constants';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

import { deletePushToken, putPushToken } from './api';
import { getJson, setJson } from './prefs';
import { emitRefresh } from './refreshBus';

const ENABLED_KEY = 'push.enabled';

export type PushOutcome = 'enabled' | 'denied' | 'unavailable';

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: false,
    shouldSetBadge: false,
  }),
});

function projectId(): string | null {
  const id = (Constants.expoConfig?.extra as { eas?: { projectId?: string } } | undefined)?.eas
    ?.projectId;
  return id ? id : null;
}

export const isPushEnabled = () => getJson<boolean>(ENABLED_KEY, false);

export const pushAvailable = () => projectId() !== null;

export async function enablePush(): Promise<PushOutcome> {
  const id = projectId();
  if (!id) return 'unavailable';
  if (Platform.OS === 'android') {
    await Notifications.setNotificationChannelAsync('default', {
      name: 'Default',
      importance: Notifications.AndroidImportance.DEFAULT,
    });
  }
  let { status } = await Notifications.getPermissionsAsync();
  if (status !== 'granted') ({ status } = await Notifications.requestPermissionsAsync());
  if (status !== 'granted') return 'denied';
  const { data } = await Notifications.getExpoPushTokenAsync({ projectId: id });
  await putPushToken(data);
  await setJson(ENABLED_KEY, true);
  return 'enabled';
}

export async function disablePush(): Promise<void> {
  await deletePushToken();
  await setJson(ENABLED_KEY, false);
}

/** Refresh screens whenever a notification arrives or is tapped. Returns an unsubscribe. */
export function listenForNotifications(): () => void {
  const received = Notifications.addNotificationReceivedListener(emitRefresh);
  const tapped = Notifications.addNotificationResponseReceivedListener(emitRefresh);
  return () => {
    received.remove();
    tapped.remove();
  };
}
