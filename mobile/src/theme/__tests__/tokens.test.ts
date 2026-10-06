import { contrastRatio, hue } from '../contrast';
import { brand, darkPalette, lightPalette, type Palette } from '../palette';
import { MIN_TARGET, space, type } from '../typography';

const AA_TEXT = 4.5;
const THEMES: [string, Palette][] = [
  ['light', lightPalette],
  ['dark', darkPalette],
];

// Every foreground/background pair the app sets text on, by token name.
const TEXT_PAIRS: [keyof Palette, keyof Palette][] = [
  ['text', 'bg'],
  ['text', 'surface'],
  ['text', 'elevated'],
  ['text', 'muted'],
  ['text', 'drawer'],
  ['textMuted', 'bg'],
  ['textMuted', 'surface'],
  ['textMuted', 'muted'],
  ['textMuted', 'drawer'],
  ['accentText', 'bg'],
  ['accentText', 'surface'],
  ['accentText', 'muted'],
  ['accentText', 'accentSoft'],
  ['accentText', 'drawer'],
  ['accentOn', 'accent'],
  ['danger', 'bg'],
  ['danger', 'surface'],
  ['danger', 'dangerSoft'],
  ['dangerOn', 'danger'],
  ['warn', 'bg'],
  ['warn', 'surface'],
  ['warn', 'warnSoft'],
  ['ok', 'surface'],
];

const hueDistance = (a: string, b: string) => {
  const d = Math.abs(hue(a) - hue(b));
  return Math.min(d, 360 - d);
};

describe('theme tokens', () => {
  it('uses the brand colours as given', () => {
    expect(brand).toEqual({ ink: '#0B0D10', ivory: '#F7F3EA', teal: '#00D1C1' });
    expect(lightPalette.bg).toBe(brand.ivory);
    expect(lightPalette.text).toBe(brand.ink);
    expect(darkPalette.bg).toBe(brand.ink);
    expect(darkPalette.text).toBe(brand.ivory);
    expect(lightPalette.accent).toBe(brand.teal);
    expect(darkPalette.accent).toBe(brand.teal);
  });

  it('defines the same tokens in both themes, all opaque hex except the scrim', () => {
    expect(Object.keys(darkPalette).sort()).toEqual(Object.keys(lightPalette).sort());
    for (const [, p] of THEMES) {
      for (const [name, value] of Object.entries(p)) {
        if (name === 'overlay') expect(value).toMatch(/^rgba\(/);
        else expect(value).toMatch(/^#[0-9A-F]{6}$/);
      }
    }
  });

  it.each(THEMES)('meets WCAG AA (4.5:1) for every text pair in %s', (_name, p) => {
    for (const [fg, bg] of TEXT_PAIRS) {
      const ratio = contrastRatio(p[fg], p[bg]);
      if (ratio < AA_TEXT) throw new Error(`${fg} on ${bg}: ${ratio.toFixed(2)}:1`);
    }
  });

  it.each(THEMES)('keeps warning and destructive far from teal in %s', (_name, p) => {
    expect(hueDistance(p.danger, brand.teal)).toBeGreaterThan(120);
    expect(hueDistance(p.warn, brand.teal)).toBeGreaterThan(120);
    expect(hueDistance(p.danger, p.warn)).toBeGreaterThan(20);
  });

  it('never sets raw teal as text on ivory (1.7:1)', () => {
    expect(contrastRatio(brand.teal, brand.ivory)).toBeLessThan(2);
    expect(lightPalette.accentText).not.toBe(brand.teal);
  });

  it('keeps spacing on the 8-pt grid and targets at 44pt', () => {
    for (const [name, value] of Object.entries(space)) {
      if (name === 'xs') expect(value).toBe(4);
      else expect(value % 8).toBe(0);
    }
    expect(MIN_TARGET).toBe(44);
  });

  it('tightens tracking as type grows', () => {
    expect(type.largeTitle.letterSpacing).toBeLessThan(type.title2.letterSpacing as number);
    expect(type.title2.letterSpacing).toBeLessThan(type.footnote.letterSpacing as number);
    expect(type.caption.letterSpacing).toBeGreaterThan(0);
  });
});
