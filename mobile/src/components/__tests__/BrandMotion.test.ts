import { readdirSync, readFileSync, statSync } from 'fs';
import { join } from 'path';

import { INTRO_FROM_DEG, INTRO_FROM_OPACITY, INTRO_FROM_SCALE } from '../brand/Spark';

const MOBILE = join(__dirname, '..', '..', '..');

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === '__tests__' ? [] : sourceFiles(path);
    return /\.(ts|tsx)$/.test(name) ? [path] : [];
  });
}

describe('brand motion', () => {
  it('only the reply avatar may animate the mark (the header logo stays still)', () => {
    const roots = [join(MOBILE, 'src'), join(MOBILE, 'app')];
    const animating = roots
      .flatMap(sourceFiles)
      .filter((path) => !/brand[\\/](Spark|LaunchIntro)\.tsx$/.test(path))
      .filter((path) => /state=["{][^}]*thinking|thinking=\{/.test(readFileSync(path, 'utf8')))
      .map((path) => path.slice(MOBILE.length + 1));
    expect(animating).toEqual(['src/components/chat/Message.tsx']);
  });

  it('starts the intro from the pose the native splash draws', () => {
    const script = readFileSync(join(MOBILE, 'scripts', 'render-brand.mjs'), 'utf8');
    const value = (name: string) =>
      Function(`return (${new RegExp(`const ${name} = ([^;]+);`).exec(script)?.[1]})`)() as number;
    expect(value('INTRO_FROM_SCALE')).toBe(INTRO_FROM_SCALE);
    expect(value('INTRO_FROM_OPACITY')).toBe(INTRO_FROM_OPACITY);
    expect(value('INTRO_FROM_DEG')).toBeCloseTo(INTRO_FROM_DEG);
    // A rotating reveal: a little over one turn, from about 60% size.
    expect(INTRO_FROM_DEG).toBeLessThanOrEqual(-360);
    expect(INTRO_FROM_DEG).toBeGreaterThanOrEqual(-450);
    expect(INTRO_FROM_SCALE).toBeCloseTo(0.6);
  });
});
