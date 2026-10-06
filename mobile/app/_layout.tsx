import { Inter_400Regular } from '@expo-google-fonts/inter/400Regular';
import { Inter_500Medium } from '@expo-google-fonts/inter/500Medium';
import { Inter_600SemiBold } from '@expo-google-fonts/inter/600SemiBold';
import { Newsreader_500Medium } from '@expo-google-fonts/newsreader/500Medium';
import { useFonts } from 'expo-font';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { AppState, View } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';

import { PairForm } from '../src/components/PairForm';
import { Loading, Title } from '../src/components/ui';
import { Screen } from '../src/components/Screen';
import { AgentStatusProvider } from '../src/lib/AgentStatus';
import { registerBackgroundSync } from '../src/lib/backgroundTasks';
import { flushSmsQueue, refreshDefaultSenders } from '../src/lib/bankSms';
import { ConversationsProvider } from '../src/lib/Conversations';
import { processDeviceCommands } from '../src/lib/deviceCommands';
import { listenForNotifications } from '../src/lib/push';
import { PairingProvider, usePairing } from '../src/lib/PairingContext';
import { emitRefresh } from '../src/lib/refreshBus';
import { ThemeProvider, useTheme } from '../src/theme';

/** Work done whenever the app is in the foreground and paired. Failures are retried next time. */
async function foregroundSync(): Promise<void> {
  await refreshDefaultSenders();
  await Promise.allSettled([flushSmsQueue(), processDeviceCommands()]);
  emitRefresh();
}

function Gate() {
  const { pairing } = usePairing();
  const { palette } = useTheme();
  const paired = pairing != null;

  useEffect(() => {
    if (!paired) return;
    void foregroundSync();
    void registerBackgroundSync().catch(() => undefined);
    const stopNotifications = listenForNotifications();
    const sub = AppState.addEventListener('change', (state) => {
      if (state === 'active') void foregroundSync();
    });
    return () => {
      stopNotifications();
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
  if (pairing === null) {
    return (
      <Screen>
        <Title>Pair with your agent</Title>
        <PairForm />
      </Screen>
    );
  }
  return (
    <AgentStatusProvider>
      <ConversationsProvider>
        <Stack
          screenOptions={{ headerShown: false, contentStyle: { backgroundColor: palette.bg } }}
        >
          <Stack.Screen name="(drawer)" />
          <Stack.Screen name="mail/[account]/[id]" />
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
    Newsreader_500Medium,
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
