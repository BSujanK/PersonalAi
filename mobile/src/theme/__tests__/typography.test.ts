import { readdirSync, readFileSync, statSync } from 'fs';
import { join } from 'path';

import { FONT_FACES, TYPE_SCALE, type, type TypeName } from '../typography';

const MOBILE = join(__dirname, '..', '..', '..');
const read = (path: string) => readFileSync(join(MOBILE, path), 'utf8');

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === '__tests__' ? [] : sourceFiles(path);
    return /\.(ts|tsx)$/.test(name) ? [path] : [];
  });
}

const ALL = Object.entries(TYPE_SCALE) as [TypeName, (typeof TYPE_SCALE)[TypeName]][];
const BUNDLED = new Set<string>(Object.values(FONT_FACES));

describe('type scale', () => {
  it('defines every role the design calls for, plus numeric variants', () => {
    expect(Object.keys(TYPE_SCALE).sort()).toEqual(
      [
        'display',
        'title1',
        'title2',
        'title3',
        'headline',
        'body',
        'callout',
        'subheadline',
        'footnote',
        'caption',
        'numberHero',
        'numberLarge',
        'number',
        'numberSmall',
      ].sort(),
    );
  });

  it.each(ALL)('%s uses a bundled face with room for its glyphs', (name, spec) => {
    const style = type[name];
    expect(BUNDLED.has(style.fontFamily as string)).toBe(true);
    // No synthetic weight over a bundled face (Android fakes bold).
    expect(style.fontWeight).toBeUndefined();
    expect(spec.lineHeight).toBeGreaterThanOrEqual(Math.ceil(spec.size * 1.15));
  });

  it('sets display text in the serif and UI text in the grotesk', () => {
    for (const name of ['display', 'title1', 'title2', 'numberHero', 'numberLarge'] as const) {
      expect(TYPE_SCALE[name].face).toBe('serif');
    }
    for (const name of ['headline', 'body', 'callout', 'subheadline', 'footnote', 'caption']) {
      expect(TYPE_SCALE[name as TypeName].face).toBe('sans');
    }
  });

  it('tightens tracking as size grows and opens it on small labels', () => {
    const bySize = [...ALL].map(([, s]) => s).sort((a, b) => b.size - a.size);
    for (let i = 1; i < bySize.length; i += 1) {
      expect(bySize[i - 1].tracking).toBeLessThanOrEqual(bySize[i].tracking + 1e-9);
    }
    expect(TYPE_SCALE.display.tracking).toBeLessThan(0);
    expect(TYPE_SCALE.caption.tracking).toBeGreaterThan(0);
  });

  it('gives every numeric variant tabular figures', () => {
    for (const [name, spec] of ALL) {
      if (!name.startsWith('number')) continue;
      expect(spec.numeric).toBe(true);
      expect(type[name].fontVariant).toEqual(['tabular-nums']);
    }
  });
});

describe('bundled fonts', () => {
  it('loads exactly the faces the scale uses, and nothing else', () => {
    const layout = read('app/_layout.tsx');
    for (const face of BUNDLED) expect(layout).toContain(face);
    const loaded = [...layout.matchAll(/^\s+((?:Newsreader|HankenGrotesk)_\w+),$/gm)].map(
      (m) => m[1],
    );
    expect(new Set(loaded)).toEqual(BUNDLED);
  });

  it('ships only open-license font packages, and no unused ones', () => {
    const pkg = JSON.parse(read('package.json')) as { dependencies: Record<string, string> };
    const fonts = Object.keys(pkg.dependencies).filter((d) => d.startsWith('@expo-google-fonts/'));
    expect(fonts.sort()).toEqual([
      '@expo-google-fonts/hanken-grotesk',
      '@expo-google-fonts/newsreader',
    ]);
    for (const name of fonts) {
      const license = readFileSync(join(MOBILE, 'node_modules', name, 'LICENSE_FONT'), 'utf8');
      expect(license).toContain('SIL Open Font License');
    }
  });

  it('never names a face outside the bundled set', () => {
    const roots = [join(MOBILE, 'src'), join(MOBILE, 'app')];
    const offenders = roots
      .flatMap(sourceFiles)
      .filter((path) => /['"](Inter|Tiempos|Styrene)[\w ]*['"_]/.test(readFileSync(path, 'utf8')));
    expect(offenders).toEqual([]);
  });
});
