import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import * as SystemUI from 'expo-system-ui';
import { Appearance, StyleSheet, useColorScheme } from 'react-native';

import { getJson, setJson } from '../lib/prefs';
import { darkPalette, lightPalette, type Palette } from './palette';

export {
  fontFamily,
  MAX_CHROME_SCALE,
  MIN_TARGET,
  radius,
  ROW_INSET,
  size,
  space,
  type,
} from './typography';
export { motion } from './motion';
export { brand, darkPalette, lightPalette } from './palette';
export type { Palette } from './palette';

export type ThemePreference = 'system' | 'light' | 'dark';
export type Scheme = 'light' | 'dark';

export interface Theme {
  palette: Palette;
  scheme: Scheme;
  preference: ThemePreference;
  setPreference: (preference: ThemePreference) => void;
}

const PREF_KEY = 'theme';

const ThemeContext = createContext<Theme>({
  palette: lightPalette,
  scheme: 'light',
  preference: 'system',
  setPreference: () => undefined,
});

function isPreference(value: unknown): value is ThemePreference {
  return value === 'system' || value === 'light' || value === 'dark';
}

/** Follows the system scheme unless the owner picked one; Appearance makes native views follow. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const system = useColorScheme();
  const [preference, setPreferenceState] = useState<ThemePreference>('system');

  useEffect(() => {
    let cancelled = false;
    void getJson<unknown>(PREF_KEY, 'system').then((stored) => {
      if (!cancelled && isPreference(stored)) setPreferenceState(stored);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    Appearance.setColorScheme(preference === 'system' ? 'unspecified' : preference);
  }, [preference]);

  const setPreference = useCallback((next: ThemePreference) => {
    setPreferenceState(next);
    void setJson(PREF_KEY, next).catch(() => undefined);
  }, []);

  const scheme: Scheme =
    preference === 'system' ? (system === 'dark' ? 'dark' : 'light') : preference;
  const value = useMemo<Theme>(
    () => ({
      palette: scheme === 'dark' ? darkPalette : lightPalette,
      scheme,
      preference,
      setPreference,
    }),
    [scheme, preference, setPreference],
  );
  // The window behind the app (visible while the keyboard resizes the layout) follows the theme.
  const background = value.palette.bg;
  useEffect(() => {
    void SystemUI.setBackgroundColorAsync(background).catch(() => undefined);
  }, [background]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export const useTheme = () => useContext(ThemeContext);

/** Build a StyleSheet from the current palette. `factory` must be defined at module scope. */
export function useThemedStyles<T extends StyleSheet.NamedStyles<T>>(
  factory: (palette: Palette) => T,
): T {
  const { palette } = useTheme();
  return useMemo(() => StyleSheet.create(factory(palette)), [factory, palette]);
}
