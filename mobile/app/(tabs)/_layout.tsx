import { Tabs } from 'expo-router';

import { FloatingTabBar } from '../../src/components/nav/FloatingTabBar';
import { useTheme } from '../../src/theme';

/**
 * Three peers under a floating pill tab bar: Money | Chat | Approvals. Chat is the centre and the
 * home: the app opens on it. Switching tabs never animates the screens (tabs are peers, not a
 * hierarchy); only the bar's violet pill moves.
 */
export default function TabsLayout() {
  const { palette } = useTheme();
  return (
    <Tabs
      initialRouteName="index"
      backBehavior="initialRoute"
      tabBar={(props) => <FloatingTabBar {...props} />}
      screenOptions={{
        headerShown: false,
        animation: 'none',
        sceneStyle: { backgroundColor: palette.bg },
      }}
    >
      <Tabs.Screen name="money" options={{ title: 'Money' }} />
      <Tabs.Screen name="index" options={{ title: 'Chat' }} />
      <Tabs.Screen name="approvals" options={{ title: 'Approvals' }} />
    </Tabs>
  );
}
