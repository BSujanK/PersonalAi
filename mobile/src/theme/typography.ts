// Inter (SIL Open Font License), bundled so Android renders the same hierarchy on every phone.
// The scale follows the HIG text styles: hierarchy comes from size, weight and leading together,
// and tracking is size-specific (negative on display sizes, slightly positive on small text).
// Sizes are base values: React Native scales them with the system font size (Dynamic Type), so
// nothing that holds text has a fixed height.
import { Platform, type TextStyle } from 'react-native';

export const fontFamily = {
  body: 'Inter_400Regular',
  bodyMedium: 'Inter_500Medium',
  bodySemiBold: 'Inter_600SemiBold',
  bodyBold: 'Inter_700Bold',
  /** Large titles and greetings. */
  display: 'Inter_700Bold',
  mono:
    Platform.select({ android: 'monospace', ios: 'Menlo', default: 'monospace' }) ?? 'monospace',
} as const;

/** Largest text scale the fixed-height chrome (nav bar title, badges) is allowed to reach. */
export const MAX_CHROME_SCALE = 1.5;

/** Minimum touch target in points (HIG 44pt; Android's 48dp is met with hitSlop on icons). */
export const MIN_TARGET = 44;

type TextStyleName =
  | 'hero'
  | 'largeTitle'
  | 'title1'
  | 'title2'
  | 'title3'
  | 'headline'
  | 'body'
  | 'callout'
  | 'subhead'
  | 'footnote'
  | 'caption';

/** Text styles without colour. Pair with a palette colour at the use site. */
export const type: Record<TextStyleName, TextStyle> = {
  /** The one big figure per screen (today's spend, total balance). Tabular so it never jitters. */
  hero: {
    fontFamily: fontFamily.display,
    fontSize: 46,
    lineHeight: 54,
    letterSpacing: -1.4,
    fontVariant: ['tabular-nums'],
  },
  largeTitle: { fontFamily: fontFamily.display, fontSize: 34, lineHeight: 41, letterSpacing: -0.6 },
  title1: { fontFamily: fontFamily.display, fontSize: 28, lineHeight: 34, letterSpacing: -0.5 },
  title2: { fontFamily: fontFamily.bodyBold, fontSize: 22, lineHeight: 28, letterSpacing: -0.3 },
  title3: {
    fontFamily: fontFamily.bodySemiBold,
    fontSize: 20,
    lineHeight: 25,
    letterSpacing: -0.2,
  },
  headline: {
    fontFamily: fontFamily.bodySemiBold,
    fontSize: 17,
    lineHeight: 22,
    letterSpacing: -0.2,
  },
  body: { fontFamily: fontFamily.body, fontSize: 17, lineHeight: 24, letterSpacing: -0.2 },
  callout: { fontFamily: fontFamily.body, fontSize: 16, lineHeight: 21, letterSpacing: -0.1 },
  subhead: { fontFamily: fontFamily.body, fontSize: 15, lineHeight: 20, letterSpacing: -0.1 },
  footnote: { fontFamily: fontFamily.body, fontSize: 13, lineHeight: 18, letterSpacing: 0 },
  caption: { fontFamily: fontFamily.body, fontSize: 12, lineHeight: 16, letterSpacing: 0.1 },
};

/** Font sizes by role, for the few places that set a size without a full text style. */
export const size = {
  caption: 12,
  small: 13,
  subhead: 15,
  body: 17,
  title: 22,
  hero: 46,
} as const;

/** 8-pt grid. `xs` is the half step for tight icon/text pairs; everything else is a multiple of 8. */
export const space = {
  xs: 4,
  sm: 8,
  md: 16,
  lg: 24,
  xl: 32,
  xxl: 48,
} as const;

export const radius = {
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  /** List cards and Quick Access cards. */
  card: 20,
  /** The floating tab bar and the hero panel. */
  xxl: 28,
  pill: 999,
} as const;

/** Leading inset of grouped list rows and their separators. */
export const ROW_INSET = space.md;
