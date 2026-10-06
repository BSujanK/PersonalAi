// Typography: an editorial serif for display text and figures, paired with a clean grotesk for
// everything you read at work size. Both are SIL Open Font License faces, bundled with the app
// (expo-font), so every Android phone renders the same hierarchy.
//
// - Newsreader (Production Type): a screen-first text serif with warm, slightly calligraphic
//   details. It holds up at title sizes without turning stiff, and its default figures are
//   tabular, so money in the display face never jitters.
// - Hanken Grotesk: a geometric-humanist grotesk, open at small sizes, with tabular digits by
//   default (it needs no `tnum` feature, which Android does not always apply).
//
// The scale follows the HIG text styles. Hierarchy comes from face, size, weight and leading
// together; tracking is tuned per size (tighter on large text, slightly open on small labels).
// Sizes are base values: React Native scales them with the system font size, and nothing that
// holds body text has a fixed height, so text grows to 200% without clipping. Fixed-height chrome
// (tab labels, badges) caps its own scale at MAX_CHROME_SCALE.
import { Platform, type TextStyle } from 'react-native';

/** Every face the app bundles. `app/_layout.tsx` loads exactly these, keyed by these names. */
export const FONT_FACES = {
  serif500: 'Newsreader_500Medium',
  serif600: 'Newsreader_600SemiBold',
  sans400: 'HankenGrotesk_400Regular',
  sans500: 'HankenGrotesk_500Medium',
  sans600: 'HankenGrotesk_600SemiBold',
  sans700: 'HankenGrotesk_700Bold',
} as const;

export const fontFamily = {
  body: FONT_FACES.sans400,
  bodyMedium: FONT_FACES.sans500,
  bodySemiBold: FONT_FACES.sans600,
  bodyBold: FONT_FACES.sans700,
  /** Display text, large titles and the wordmark. */
  display: FONT_FACES.serif500,
  displayStrong: FONT_FACES.serif600,
  mono:
    Platform.select({ android: 'monospace', ios: 'Menlo', default: 'monospace' }) ?? 'monospace',
} as const;

/** Largest text scale the fixed-height chrome (tab labels, badges) is allowed to reach. */
export const MAX_CHROME_SCALE = 1.5;

/** Minimum touch target in points (HIG 44pt; Android's 48dp is met with hitSlop on icons). */
export const MIN_TARGET = 44;

type Face = 'serif' | 'sans';
type Weight = 400 | 500 | 600 | 700;

export interface TypeSpec {
  face: Face;
  weight: Weight;
  size: number;
  lineHeight: number;
  /** Letter spacing in points: negative on large sizes, slightly open on small labels. */
  tracking: number;
  /** Money and counts: tabular figures so columns and count-ups never jitter. */
  numeric?: boolean;
}

export type TypeName =
  | 'display'
  | 'title1'
  | 'title2'
  | 'title3'
  | 'headline'
  | 'body'
  | 'callout'
  | 'subheadline'
  | 'footnote'
  | 'caption'
  | 'numberHero'
  | 'numberLarge'
  | 'number'
  | 'numberSmall';

/** The type scale. Weight is the face's weight; React Native picks it by family name. */
export const TYPE_SCALE: Record<TypeName, TypeSpec> = {
  display: { face: 'serif', weight: 500, size: 34, lineHeight: 40, tracking: -0.7 },
  title1: { face: 'serif', weight: 500, size: 28, lineHeight: 34, tracking: -0.5 },
  title2: { face: 'serif', weight: 500, size: 23, lineHeight: 29, tracking: -0.3 },
  title3: { face: 'sans', weight: 600, size: 19, lineHeight: 25, tracking: -0.25 },
  headline: { face: 'sans', weight: 600, size: 16, lineHeight: 22, tracking: -0.1 },
  body: { face: 'sans', weight: 400, size: 16, lineHeight: 24, tracking: -0.05 },
  callout: { face: 'sans', weight: 400, size: 15, lineHeight: 21, tracking: 0 },
  subheadline: { face: 'sans', weight: 400, size: 14, lineHeight: 20, tracking: 0.05 },
  footnote: { face: 'sans', weight: 400, size: 13, lineHeight: 18, tracking: 0.1 },
  caption: { face: 'sans', weight: 500, size: 12, lineHeight: 16, tracking: 0.3 },
  numberHero: {
    face: 'serif',
    weight: 500,
    size: 48,
    lineHeight: 56,
    tracking: -1.2,
    numeric: true,
  },
  numberLarge: {
    face: 'serif',
    weight: 500,
    size: 28,
    lineHeight: 34,
    tracking: -0.4,
    numeric: true,
  },
  number: { face: 'sans', weight: 600, size: 15, lineHeight: 21, tracking: 0, numeric: true },
  numberSmall: {
    face: 'sans',
    weight: 500,
    size: 13,
    lineHeight: 18,
    tracking: 0.1,
    numeric: true,
  },
};

const FAMILY: Record<Face, Partial<Record<Weight, string>>> = {
  serif: { 500: FONT_FACES.serif500, 600: FONT_FACES.serif600 },
  sans: {
    400: FONT_FACES.sans400,
    500: FONT_FACES.sans500,
    600: FONT_FACES.sans600,
    700: FONT_FACES.sans700,
  },
};

/** The bundled family for a face and weight; throws for a pair that is not bundled. */
export function familyFor(face: Face, weight: Weight): string {
  const family = FAMILY[face][weight];
  if (!family) throw new Error(`no bundled ${face} face at weight ${weight}`);
  return family;
}

function toStyle(spec: TypeSpec): TextStyle {
  return {
    // No fontWeight: Android would synthesise a fake bold over the bundled face.
    fontFamily: familyFor(spec.face, spec.weight),
    fontSize: spec.size,
    lineHeight: spec.lineHeight,
    letterSpacing: spec.tracking,
    ...(spec.numeric ? { fontVariant: ['tabular-nums' as const] } : null),
  };
}

/** Text styles without colour. Pair with a palette colour at the use site. */
export const type = Object.fromEntries(
  Object.entries(TYPE_SCALE).map(([name, spec]) => [name, toStyle(spec)]),
) as Record<TypeName, TextStyle>;

/** Font sizes by role, for the few places that set a size without a full text style. */
export const size = {
  caption: TYPE_SCALE.caption.size,
  small: TYPE_SCALE.footnote.size,
  subhead: TYPE_SCALE.subheadline.size,
  body: TYPE_SCALE.body.size,
  title: TYPE_SCALE.title2.size,
  hero: TYPE_SCALE.numberHero.size,
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
