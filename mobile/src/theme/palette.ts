// Theme tokens, light and dark, derived from three brand colours. The measured WCAG contrast of
// every text pair is checked in src/theme/__tests__/tokens.test.ts (AA: 4.5:1 for text).
//
// - Ink black #0B0D10: dark background, light-mode text.
// - Warm ivory #F7F3EA: light background, dark-mode text.
// - Electric teal #00D1C1: primary accent, links, active states.
//
// Teal on ivory is only 1.7:1, so light mode never sets text in raw teal: filled accents carry ink
// text (10.1:1) and teal text uses `accentText`, a deeper teal of the same hue (5.8:1 on ivory).
// Warning (amber) and destructive (red) sit far from teal on the colour wheel in both themes.

export const brand = {
  ink: '#0B0D10',
  ivory: '#F7F3EA',
  teal: '#00D1C1',
} as const;

export interface Palette {
  /** Screen background; grouped lists sit directly on it. */
  bg: string;
  /** Drawer background, one step away from the screen. */
  drawer: string;
  /** Grouped list cells, cards and the composer. */
  surface: string;
  /** Raised surfaces over `surface`: sheets, menus, the collapsed nav bar. */
  elevated: string;
  /** Quiet fills: user bubbles, chips, code wells, segmented control tracks. */
  muted: string;
  /** Control outlines. */
  border: string;
  /** Hairlines between rows and under the nav bar. */
  separator: string;
  text: string;
  /** Secondary text: subtitles, captions, section headers. */
  textMuted: string;
  /** Filled accent: primary buttons, the send button, selected segment. */
  accent: string;
  /** Text and icons on `accent`. */
  accentOn: string;
  /** Teal for text and icons on bg/surface: links, active states. */
  accentText: string;
  /** Tinted accent fill (tinted buttons, selected rows); `accentText` reads on it. */
  accentSoft: string;
  /** Destructive and the "anyone with the link" warning. Text on bg/surface. */
  danger: string;
  dangerOn: string;
  dangerSoft: string;
  /** Caution: NEW recipients, stored copies, expiring approvals. Text on bg/surface. */
  warn: string;
  warnSoft: string;
  /** Success marks. Teal: the brand's own "done" colour. */
  ok: string;
  /** Scrim behind the drawer and sheets. */
  overlay: string;
}

export const lightPalette: Palette = {
  bg: brand.ivory,
  drawer: '#F0EBDF',
  surface: '#FFFDF8',
  elevated: '#FFFDF8',
  muted: '#ECE6D9',
  border: '#D3CCBD',
  separator: '#DDD6C8',
  text: brand.ink,
  textMuted: '#5C5A55',
  accent: brand.teal,
  accentOn: brand.ink,
  accentText: '#006B63',
  accentSoft: '#D3EFEA',
  danger: '#B42318',
  dangerOn: '#FFFFFF',
  dangerSoft: '#F8E1DC',
  warn: '#8A5300',
  warnSoft: '#F6E7C8',
  ok: '#006B63',
  overlay: 'rgba(11, 13, 16, 0.4)',
};

export const darkPalette: Palette = {
  bg: brand.ink,
  drawer: '#111418',
  surface: '#171A1F',
  elevated: '#1E2228',
  muted: '#22272E',
  border: '#333944',
  separator: '#2A2F37',
  text: brand.ivory,
  textMuted: '#A6A39C',
  accent: brand.teal,
  accentOn: brand.ink,
  accentText: brand.teal,
  accentSoft: '#0B2F2D',
  danger: '#FF6B5E',
  dangerOn: brand.ink,
  dangerSoft: '#3A1714',
  warn: '#F5B03B',
  warnSoft: '#33270F',
  ok: brand.teal,
  overlay: 'rgba(0, 0, 0, 0.6)',
};
