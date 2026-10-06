// Theme tokens, dark-first, with a light theme derived from the same hues. The measured WCAG
// contrast of every text pair is checked in src/theme/__tests__/tokens.test.ts (AA: 4.5:1).
//
// Dark: near-black ink at the bottom of every screen, blending up into a deep violet glow at the
// top. Surfaces step up ink -> surface -> raised. Violet is the one accent:
// - #8B5CF6 is the accent itself: the active tab pill, icons, dots, chart bars, the spark.
// - #A78BFA is violet *text* on dark (links, active labels): 7.4:1 on ink.
// - #6D28D9 is the glow behind the header and the fill under white text: raw #8B5CF6 under white
//   text is only 4.2:1, so filled buttons sit on #6D28D9 (7.1:1) with an #8B5CF6 top highlight.
// Success, danger and warning sit far from violet on the colour wheel in both themes.

export const brand = {
  ink: '#07060B',
  surface: '#121019',
  raised: '#1B1726',
  violet: '#8B5CF6',
  violetLight: '#A78BFA',
  violetGlow: '#6D28D9',
  text: '#F5F3FF',
  muted: '#A1A1B5',
  success: '#22C55E',
  danger: '#EF4444',
  warning: '#F59E0B',
} as const;

export interface Palette {
  /** Screen background (the ink the glow fades into). */
  bg: string;
  /** Top of the screen glow; the background gradient starts here. */
  glow: string;
  /** Cards, list rows, the composer. */
  surface: string;
  /** Raised over `surface`: sheets, menus, the floating tab bar, selected segments. */
  raised: string;
  /** Quiet fills: chips, icon tiles, code wells, segmented control tracks. */
  muted: string;
  /** Control outlines. */
  border: string;
  /** Hairlines inside a card. */
  separator: string;
  text: string;
  /** Secondary text: times, subtitles, captions, section headers. */
  textMuted: string;
  /** The accent: active tab pill, icons, dots, bars. Never under text. */
  accent: string;
  /** Fill under text: primary buttons, the send button, the user's chat bubble. */
  accentStrong: string;
  /** Text and icons on `accentStrong` (and on the active tab pill). */
  accentOn: string;
  /** Violet for text and icons on bg/surface/raised: links, active states. */
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
  /** Success: money in, done marks, online. */
  ok: string;
  okSoft: string;
  /** Translucent glass for round header buttons and the dark pill button. */
  glass: string;
  glassBorder: string;
  /** Scrim behind sheets. */
  overlay: string;
}

export const darkPalette: Palette = {
  bg: brand.ink,
  glow: '#2A1260',
  surface: brand.surface,
  raised: brand.raised,
  muted: '#241E33',
  border: '#352D4A',
  separator: '#2A2338',
  text: brand.text,
  textMuted: brand.muted,
  accent: brand.violet,
  accentStrong: brand.violetGlow,
  accentOn: '#FFFFFF',
  accentText: brand.violetLight,
  accentSoft: '#251A45',
  danger: brand.danger,
  dangerOn: brand.ink,
  dangerSoft: '#2A1016',
  warn: brand.warning,
  warnSoft: '#2B1F0A',
  ok: brand.success,
  okSoft: '#0E2617',
  glass: 'rgba(255, 255, 255, 0.07)',
  glassBorder: 'rgba(255, 255, 255, 0.10)',
  overlay: 'rgba(4, 3, 8, 0.66)',
};

// Light: the same hues on a pale lavender ground. Violet text deepens to the glow hue, and the
// status colours darken until they read as text on white.
export const lightPalette: Palette = {
  bg: '#F6F4FB',
  glow: '#DCCEFC',
  surface: '#FFFFFF',
  raised: '#FFFFFF',
  muted: '#EEEAF7',
  border: '#D8D1E8',
  separator: '#E7E2F1',
  text: '#16121F',
  textMuted: '#5D5970',
  accent: brand.violet,
  accentStrong: brand.violetGlow,
  accentOn: '#FFFFFF',
  accentText: brand.violetGlow,
  accentSoft: '#EDE6FE',
  danger: '#B91C1C',
  dangerOn: '#FFFFFF',
  dangerSoft: '#FDE8E8',
  warn: '#92400E',
  warnSoft: '#FDF0D9',
  ok: '#166534',
  okSoft: '#E3F6EA',
  glass: 'rgba(22, 18, 31, 0.05)',
  glassBorder: 'rgba(22, 18, 31, 0.08)',
  overlay: 'rgba(22, 18, 31, 0.40)',
};
