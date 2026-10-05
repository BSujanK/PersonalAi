// Newsreader (serif, display) and Inter (sans, body); both SIL Open Font License.
// Sizes are base values: React Native scales them with the system font size (dynamic type).
import { Platform } from 'react-native';

export const fontFamily = {
  display: 'Newsreader_500Medium',
  body: 'Inter_400Regular',
  bodyMedium: 'Inter_500Medium',
  bodySemiBold: 'Inter_600SemiBold',
  mono: Platform.select({ android: 'monospace', default: 'Menlo' }) ?? 'monospace',
} as const;

/** Largest text scale the fixed-height chrome (headers, chips, buttons) is allowed to reach. */
export const MAX_CHROME_SCALE = 1.5;

export const MIN_TARGET = 44;

export const size = {
  caption: 12,
  small: 13,
  body: 16,
  title: 24,
  hero: 32,
} as const;
