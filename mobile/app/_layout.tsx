import { HankenGrotesk_400Regular } from '@expo-google-fonts/hanken-grotesk/400Regular';
import { HankenGrotesk_500Medium } from '@expo-google-fonts/hanken-grotesk/500Medium';
import { HankenGrotesk_600SemiBold } from '@expo-google-fonts/hanken-grotesk/600SemiBold';
import { HankenGrotesk_700Bold } from '@expo-google-fonts/hanken-grotesk/700Bold';
import { Newsreader_500Medium } from '@expo-google-fonts/newsreader/500Medium';
import { Newsreader_600SemiBold } from '@expo-google-fonts/newsreader/600SemiBold';
import { useFonts } from 'expo-font';
import * as Notifications from 'expo-notifications';
import { router, Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { AppState, View } from 'react-native';
import { useReducedMotion } from 'react-native-reanimated';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';

import { IntroProvider } from '../src/components/brand/LaunchIntro';
import { PairScreen } from '../src/components/PairScreen';
import { ToastHost } from '../src/components/Toast';
import { Loading } from '../src/components/ui';
import { AgentStatusProvider } from '../src/lib/AgentStatus';
import { checkAlerts, handleAlertResponse, requestAlertPermission } from '../src/lib/alerts';
import { registerBackgroundSync } from '../src/lib/backgroundTasks';
import { refreshDefaultSenders } from '../src/lib/bankSms';
import { autoImportBankSms } from '../src/lib/smsAutoImport';
import { showToast } from '../src/lib/toast';
import { getJson, setJson } from '../src/lib/prefs';
import { ConversationsProvider } from '../src/lib/Conversations';
import { processDeviceCommands } from '../src/lib/deviceCommands';
import { listenForNotifications } from '../src/lib/push';
import { PairingProvider, usePairing } from '../src/lib/PairingContext';
import { emitRefresh } from '../src/lib/refreshBus';
import { ThemeProvider, useTheme } from '../src/theme';

/** Work done whenever the app is in the foreground and paired. Failures are retried next time. */
/** Import new bank SMS in the background and say so only when the server got new ones. */
async function syncBankSms(): Promise<void> {
  const result = await autoImportBankSms();
  if (result.status === 'synced' && result.fresh > 0) {
    showToast(`Synced ${result.fresh} bank message${result.fresh === 1 ? '' : 's'}`);
  }
}

async function foregroundSync(): Promise<void> {
  await refreshDefaultSenders();
  await Promise.allSettled([syncBankSms(), processDeviceCommands(), checkAlerts()]);
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
          <Stack.Screen name="inbox" />
          <Stack.Screen name="deadline/[id]" />
        </Stack>
      </ConversationsProvider>
    </AgentStatusProvider>
  );
}

function Themed() {
  const { palette, scheme } = useTheme();
  // Fonts are bundled, so this resolves almost at once. On a load error the system fonts are used.
  const [fontsLoaded, fontError] = useFonts({
    Newsreader_500Medium,
    Newsreader_600SemiBold,
    HankenGrotesk_400Regular,
    HankenGrotesk_500Medium,
    HankenGrotesk_600SemiBold,
    HankenGrotesk_700Bold,
  });
  return (
    <View style={{ flex: 1, backgroundColor: palette.bg }}>
      <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
      {fontsLoaded || fontError ? (
        <IntroProvider>
          <PairingProvider>
            <Gate />
          </PairingProvider>
          <ToastHost />
        </IntroProvider>
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
