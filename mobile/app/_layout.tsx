import { Inter_400Regular } from '@expo-google-fonts/inter/400Regular';
import { Inter_500Medium } from '@expo-google-fonts/inter/500Medium';
import { Inter_600SemiBold } from '@expo-google-fonts/inter/600SemiBold';
import { Inter_700Bold } from '@expo-google-fonts/inter/700Bold';
import { useFonts } from 'expo-font';
import * as Notifications from 'expo-notifications';
import { router, Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { AppState, View } from 'react-native';
import { useReducedMotion } from 'react-native-reanimated';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';

import { PairScreen } from '../src/components/PairScreen';
import { Loading } from '../src/components/ui';
import { AgentStatusProvider } from '../src/lib/AgentStatus';
import { checkAlerts, handleAlertResponse, requestAlertPermission } from '../src/lib/alerts';
import { registerBackgroundSync } from '../src/lib/backgroundTasks';
import { flushSmsQueue, refreshDefaultSenders } from '../src/lib/bankSms';
import { getJson, setJson } from '../src/lib/prefs';
import { ConversationsProvider } from '../src/lib/Conversations';
import { processDeviceCommands } from '../src/lib/deviceCommands';
import { listenForNotifications } from '../src/lib/push';
import { PairingProvider, usePairing } from '../src/lib/PairingContext';
import { emitRefresh } from '../src/lib/refreshBus';
import { ThemeProvider, useTheme } from '../src/theme';

/** Work done whenever the app is in the foreground and paired. Failures are retried next time. */
async function foregroundSync(): Promise<void> {
  await refreshDefaultSenders();
  await Promise.allSettled([flushSmsQueue(), processDeviceCommands(), checkAlerts()]);
  emitRefresh();
}

const PERMISSION_ASKED_KEY = 'alerts.permissionAsked';

/** Ask for notification permission once after pairing; Settings explains it and can ask again. */
async function askAlertPermissionOnce(): Promise<void> {
  if (await getJson<boolean>(PERMISSION_ASKED_KEY, false)) return;
  await setJson(PERMISSION_ASKED_KEY, true);
  await requestAlertPermission();
}

function Gate() {
  const { pairing } = usePairing();
  const { palette } = useTheme();
  const reduced = useReducedMotion();
  const paired = pairing != null;

  useEffect(() => {
    if (!paired) return;
    void askAlertPermissionOnce()
      .catch(() => undefined)
      .then(foregroundSync);
    void registerBackgroundSync().catch(() => undefined);
    const stopNotifications = listenForNotifications();
    const respond = (response: Notifications.NotificationResponse) => {
      // Cleared so a later remount does not replay a response that was already handled.
      void Notifications.clearLastNotificationResponseAsync().catch(() => undefined);
      void handleAlertResponse(response, (route) => router.push(route)).catch(() => undefined);
    };
    // A tap that launched the app from killed state arrives here, not through the listener.
    void Notifications.getLastNotificationResponseAsync()
      .then((last) => {
        if (last) respond(last);
      })
      .catch(() => undefined);
    const responses = Notifications.addNotificationResponseReceivedListener(respond);
    const sub = AppState.addEventListener('change', (state) => {
      if (state === 'active') void foregroundSync();
    });
    return () => {
      stopNotifications();
      responses.remove();
      sub.remove();
    };
  }, [paired]);

  if (pairing === undefined) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: palette.bg }}>
        <Loading />
      </SafeAreaView>
    );
  }
  if (pairing === null) return <PairScreen />;
  return (
    <AgentStatusProvider>
      <ConversationsProvider>
        {/* Deeper into the hierarchy: the platform push, unmodified; a fade with Reduce Motion. */}
        <Stack
          screenOptions={{
            headerShown: false,
            contentStyle: { backgroundColor: palette.bg },
            animation: reduced ? 'fade' : 'default',
          }}
        >
          <Stack.Screen name="(tabs)" />
          <Stack.Screen name="mail/[account]/[id]" />
          <Stack.Screen name="files" />
          <Stack.Screen name="settings" />
          <Stack.Screen name="alerts" />
          <Stack.Screen name="history" />
        </Stack>
      </ConversationsProvider>
    </AgentStatusProvider>
  );
}

function Themed() {
  const { palette, scheme } = useTheme();
  // Fonts are bundled, so this resolves almost at once. On a load error the system fonts are used.
  const [fontsLoaded, fontError] = useFonts({
    Inter_400Regular,
    Inter_500Medium,
    Inter_600SemiBold,
    Inter_700Bold,
  });
  return (
    <View style={{ flex: 1, backgroundColor: palette.bg }}>
      <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
      {fontsLoaded || fontError ? (
        <PairingProvider>
          <Gate />
        </PairingProvider>
      ) : null}
    </View>
  );
}

export default function RootLayout() {
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <ThemeProvider>
          <Themed />
        </ThemeProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
