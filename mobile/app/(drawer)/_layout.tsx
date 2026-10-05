import { Drawer } from 'expo-router/drawer';
import { useWindowDimensions } from 'react-native';

import { AppDrawerContent } from '../../src/components/drawer/DrawerContent';
import { useTheme } from '../../src/theme';

/** Chat is the home screen; the drawer holds the conversation history and the other screens. */
export default function DrawerLayout() {
  const { palette } = useTheme();
  const { width } = useWindowDimensions();
  return (
    <Drawer
      drawerContent={(props) => <AppDrawerContent {...props} />}
      screenOptions={{
        headerShown: false,
        drawerType: 'front',
        overlayColor: palette.overlay,
        drawerStyle: { width: Math.min(width * 0.84, 360), backgroundColor: palette.drawer },
        sceneStyle: { backgroundColor: palette.bg },
        swipeEdgeWidth: 40,
      }}
    >
      <Drawer.Screen name="index" options={{ title: 'Chat' }} />
      <Drawer.Screen name="today" options={{ title: 'Today' }} />
      <Drawer.Screen name="approvals" options={{ title: 'Approvals' }} />
      <Drawer.Screen name="money" options={{ title: 'Money' }} />
      <Drawer.Screen name="settings" options={{ title: 'Settings' }} />
    </Drawer>
  );
}
