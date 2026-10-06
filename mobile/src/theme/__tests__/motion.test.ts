import { readdirSync, readFileSync, statSync } from 'fs';
import { join } from 'path';

// Reanimated CSS transitions on device accept only the predefined keywords or a cubicBezier()
// object; a 'cubic-bezier(...)' string crashes the app at first render. Jest runs Reanimated's
// mock, which accepts anything, so guard the source instead.
const ROOTS = [join(__dirname, '..', '..'), join(__dirname, '..', '..', '..', 'app')];
const CSS_CUBIC_BEZIER_STRING = /['"`]\s*cubic-bezier\(/;

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === '__tests__' ? [] : sourceFiles(path);
    return /\.(ts|tsx)$/.test(name) ? [path] : [];
  });
}

it('never passes a CSS cubic-bezier string to Reanimated', () => {
  const offenders = ROOTS.flatMap(sourceFiles).filter((path) =>
    CSS_CUBIC_BEZIER_STRING.test(readFileSync(path, 'utf8')),
  );
  expect(offenders).toEqual([]);
});
