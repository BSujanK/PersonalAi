import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { AppState } from 'react-native';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';

import { PairForm } from '../src/components/PairForm';
import { Loading, Screen, Title } from '../src/components/ui';
import { registerBackgroundSync } from '../src/lib/backgroundTasks';
import { flushSmsQueue, refreshDefaultSenders } from '../src/lib/bankSms';
import { processDeviceCommands } from '../src/lib/deviceCommands';
import { listenForNotifications } from '../src/lib/push';
import { PairingProvider, usePairing } from '../src/lib/PairingContext';
import { emitRefresh } from '../src/lib/refreshBus';

/** Work done whenever the app is in the foreground and paired. Failures are retried next time. */
async function foregroundSync(): Promise<void> {
  await refreshDefaultSenders();
  await Promise.allSettled([flushSmsQueue(), processDeviceCommands()]);
  emitRefresh();
}

function Gate() {
  const { pairing } = usePairing();
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
      <SafeAreaView style={{ flex: 1 }}>
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
  return <Stack screenOptions={{ headerShown: false }} />;
}

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <StatusBar style="auto" />
      <PairingProvider>
        <Gate />
      </PairingProvider>
    </SafeAreaProvider>
  );
}
