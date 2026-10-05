// Calm warm-neutral palette, light and dark. Own colours: a sage-teal accent, not any vendor's.
// Contrast (WCAG): text on bg >= 12:1, muted on bg >= 5:1, accentOn on accent >= 5:1 in both.

export interface Palette {
  bg: string;
  /** Slightly deeper surface used by the drawer. */
  drawer: string;
  surface: string;
  /** User message bubble, chips, code blocks, input wells. */
  muted: string;
  border: string;
  text: string;
  textMuted: string;
  accent: string;
  accentOn: string;
  accentSoft: string;
  danger: string;
  dangerOn: string;
  dangerSoft: string;
  ok: string;
  warn: string;
  overlay: string;
}

export const lightPalette: Palette = {
  bg: '#F7F5F0',
  drawer: '#F0EDE5',
  surface: '#FDFCF9',
  muted: '#ECE8DF',
  border: '#DDD8CC',
  text: '#1F1D1A',
  textMuted: '#625D54',
  accent: '#2B6A5C',
  accentOn: '#FFFFFF',
  accentSoft: '#DCEAE5',
  danger: '#A8322B',
  dangerOn: '#FFFFFF',
  dangerSoft: '#F4DDDA',
  ok: '#2C7A4B',
  warn: '#8F6310',
  overlay: 'rgba(31, 29, 26, 0.4)',
};

export const darkPalette: Palette = {
  bg: '#1B1A18',
  drawer: '#161513',
  surface: '#242220',
  muted: '#2E2C29',
  border: '#3B3835',
  text: '#ECE8DF',
  textMuted: '#A8A296',
  accent: '#7DBBAA',
  accentOn: '#0F2420',
  accentSoft: '#243631',
  danger: '#EE8F87',
  dangerOn: '#2A0F0C',
  dangerSoft: '#3A2422',
  ok: '#84CBA1',
  warn: '#D9B063',
  overlay: 'rgba(0, 0, 0, 0.55)',
};
