import { useNavigation, useRouter } from 'expo-router';
import type { DrawerNavigationProp } from 'expo-router/drawer';
import type { ReactNode } from 'react';
import { RefreshControl, ScrollView, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { fontFamily, MAX_CHROME_SCALE, size, useThemedStyles, type Palette } from '../theme';
import { COLUMN_MAX, IconButton } from './ui';

const makeStyles = (p: Palette) => ({
  screen: { flex: 1, backgroundColor: p.bg },
  column: { width: '100%' as const, maxWidth: COLUMN_MAX, alignSelf: 'center' as const },
  content: { padding: 16, paddingBottom: 32, gap: 12 },
  header: {
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    gap: 4,
    paddingHorizontal: 8,
    minHeight: 56,
  },
  headerTitle: {
    flex: 1,
    fontFamily: fontFamily.display,
    fontSize: size.title,
    color: p.text,
  },
});

/** Opens the drawer. Only rendered where a drawer exists (the paired app). */
function MenuButton() {
  const navigation = useNavigation<DrawerNavigationProp<Record<string, undefined>>>();
  return <IconButton icon="menu" label="Open menu" onPress={() => navigation.toggleDrawer()} />;
}

/** Pops back to where the screen was opened from. Only for screens pushed over the drawer. */
function BackButton() {
  const router = useRouter();
  return <IconButton icon="arrow-left" label="Back" onPress={() => router.back()} />;
}

export function ScreenHeader({
  title,
  menu,
  back,
  right,
}: {
  title: string;
  menu?: boolean;
  back?: boolean;
  right?: ReactNode;
}) {
  const styles = useThemedStyles(makeStyles);
  return (
    <View style={[styles.header, styles.column]}>
      {menu ? <MenuButton /> : null}
      {back ? <BackButton /> : null}
      <Text
        accessibilityRole="header"
        maxFontSizeMultiplier={MAX_CHROME_SCALE}
        style={[styles.headerTitle, !menu && !back && { paddingLeft: 8 }]}
        numberOfLines={1}
      >
        {title}
      </Text>
      {right}
    </View>
  );
}

export function Screen({
  title,
  menu,
  back,
  children,
  refreshing,
  onRefresh,
}: {
  title?: string;
  menu?: boolean;
  back?: boolean;
  children: ReactNode;
  refreshing?: boolean;
  onRefresh?: () => void;
}) {
  const styles = useThemedStyles(makeStyles);
  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      {title ? <ScreenHeader title={title} menu={menu} back={back} /> : null}
      <ScrollView
        contentContainerStyle={[styles.content, styles.column]}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          onRefresh ? (
            <RefreshControl refreshing={refreshing ?? false} onRefresh={onRefresh} />
          ) : undefined
        }
      >
        {children}
      </ScrollView>
    </SafeAreaView>
  );
}
