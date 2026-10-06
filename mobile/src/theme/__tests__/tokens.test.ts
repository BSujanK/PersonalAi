import { contrastRatio, hue } from '../contrast';
import { brand, darkPalette, lightPalette, type Palette } from '../palette';
import { MIN_TARGET, space, type } from '../typography';

const AA_TEXT = 4.5;
const THEMES: [string, Palette][] = [
  ['light', lightPalette],
  ['dark', darkPalette],
];

/** Translucent tokens; everything else is an opaque #RRGGBB. */
const TRANSLUCENT = new Set<keyof Palette>(['overlay', 'glass', 'glassBorder']);

// Every foreground/background pair the app sets text on, by token name.
const TEXT_PAIRS: [keyof Palette, keyof Palette][] = [
  ['text', 'bg'],
  ['text', 'glow'],
  ['text', 'surface'],
  ['text', 'raised'],
  ['text', 'muted'],
  ['textMuted', 'bg'],
  ['textMuted', 'glow'],
  ['textMuted', 'surface'],
  ['textMuted', 'raised'],
  ['textMuted', 'muted'],
  ['accentText', 'bg'],
  ['accentText', 'surface'],
  ['accentText', 'raised'],
  ['accentText', 'muted'],
  ['accentText', 'accentSoft'],
  ['accentOn', 'accentStrong'],
  ['danger', 'bg'],
  ['danger', 'surface'],
  ['danger', 'raised'],
  ['danger', 'dangerSoft'],
  ['dangerOn', 'danger'],
  ['warn', 'bg'],
  ['warn', 'surface'],
  ['warn', 'warnSoft'],
  ['ok', 'surface'],
  ['ok', 'raised'],
  ['ok', 'okSoft'],
];

const hueDistance = (a: string, b: string) => {
  const d = Math.abs(hue(a) - hue(b));
  return Math.min(d, 360 - d);
};

describe('theme tokens', () => {
  it('uses the owner palette as given', () => {
    expect(darkPalette.bg).toBe('#07060B');
    expect(darkPalette.surface).toBe('#121019');
    expect(darkPalette.raised).toBe('#1B1726');
    expect(darkPalette.accent).toBe('#8B5CF6');
    expect(darkPalette.accentText).toBe('#A78BFA');
    expect(darkPalette.accentStrong).toBe('#6D28D9');
    expect(darkPalette.text).toBe('#F5F3FF');
    expect(darkPalette.textMuted).toBe('#A1A1B5');
    expect(darkPalette.ok).toBe('#22C55E');
    expect(darkPalette.danger).toBe('#EF4444');
    expect(darkPalette.warn).toBe('#F59E0B');
    // Light is derived from the same violet.
    expect(lightPalette.accent).toBe(brand.violet);
    expect(lightPalette.accentText).toBe(brand.violetGlow);
  });

  it('defines the same tokens in both themes, opaque hex except the translucent ones', () => {
    expect(Object.keys(darkPalette).sort()).toEqual(Object.keys(lightPalette).sort());
    for (const [, p] of THEMES) {
      for (const [name, value] of Object.entries(p) as [keyof Palette, string][]) {
        if (TRANSLUCENT.has(name)) expect(value).toMatch(/^rgba\(/);
        else expect([name, value]).toEqual([name, expect.stringMatching(/^#[0-9A-F]{6}$/)]);
      }
    }
  });

  it.each(THEMES)('meets WCAG AA (4.5:1) for every text pair in %s', (_name, p) => {
    for (const [fg, bg] of TEXT_PAIRS) {
      const ratio = contrastRatio(p[fg], p[bg]);
      if (ratio < AA_TEXT) throw new Error(`${fg} on ${bg}: ${ratio.toFixed(2)}:1`);
    }
  });

  it('never sets white text on the raw #8B5CF6 accent (4.2:1); fills use #6D28D9', () => {
    expect(contrastRatio('#FFFFFF', brand.violet)).toBeLessThan(AA_TEXT);
    for (const [, p] of THEMES) {
      expect(p.accentStrong).toBe(brand.violetGlow);
      expect(contrastRatio(p.accentOn, p.accentStrong)).toBeGreaterThan(7);
    }
  });

  it.each(THEMES)('keeps status colours far from violet in %s', (_name, p) => {
    expect(hueDistance(p.danger, brand.violet)).toBeGreaterThan(90);
    expect(hueDistance(p.warn, brand.violet)).toBeGreaterThan(120);
    expect(hueDistance(p.ok, brand.violet)).toBeGreaterThan(90);
    expect(hueDistance(p.danger, p.warn)).toBeGreaterThan(20);
  });

  it('keeps spacing on the 8-pt grid and targets at 44pt', () => {
    for (const [name, value] of Object.entries(space)) {
      if (name === 'xs') expect(value).toBe(4);
      else expect(value % 8).toBe(0);
    }
    expect(MIN_TARGET).toBe(44);
  });

  it('tightens tracking as type grows', () => {
    expect(type.numberHero.letterSpacing).toBeLessThan(type.display.letterSpacing as number);
    expect(type.display.letterSpacing).toBeLessThan(type.title2.letterSpacing as number);
    expect(type.title2.letterSpacing).toBeLessThan(type.footnote.letterSpacing as number);
    expect(type.caption.letterSpacing).toBeGreaterThan(0);
  });
});
