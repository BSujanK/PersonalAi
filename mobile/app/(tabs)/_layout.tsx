import { Tabs } from 'expo-router';

import { FloatingTabBar } from '../../src/components/nav/FloatingTabBar';
import { useTheme } from '../../src/theme';

/**
 * Five peers under a floating pill tab bar. Switching tabs never animates the screens (tabs are
 * peers, not a hierarchy); only the bar's violet pill moves.
 */
export default function TabsLayout() {
  const { palette } = useTheme();
  return (
    <Tabs
      tabBar={(props) => <FloatingTabBar {...props} />}
      screenOptions={{
        headerShown: false,
        animation: 'none',
        sceneStyle: { backgroundColor: palette.bg },
      }}
    >
      <Tabs.Screen name="index" options={{ title: 'Home' }} />
      <Tabs.Screen name="chat" options={{ title: 'Chat' }} />
      <Tabs.Screen name="money" options={{ title: 'Money' }} />
      <Tabs.Screen name="approvals" options={{ title: 'Approvals' }} />
      <Tabs.Screen name="more" options={{ title: 'More' }} />
    </Tabs>
  );
}
