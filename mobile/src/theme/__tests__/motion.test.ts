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

it('keeps motion tokens worklet-copyable (plain numbers only)', () => {
  // Worklets copy everything they capture; a class instance here crashes the UI thread on device
  // ("Cannot copy value of type ..."). Easing objects live outside `motion`.
  const { motion } = jest.requireActual<typeof import('../motion')>('../motion');
  for (const [key, value] of Object.entries(motion)) {
    expect([key, typeof value]).toEqual([key, 'number']);
  }
});

const sources = () => ROOTS.flatMap(sourceFiles).map((path) => [path, readFileSync(path, 'utf8')]);

/** The text of each call to `name(...)`, from its opening to its matching closing paren. */
function calls(source: string, name: RegExp): string[] {
  const found: string[] = [];
  for (const match of source.matchAll(name)) {
    let depth = 0;
    const start = (match.index ?? 0) + match[0].length - 1;
    for (let i = start; i < source.length; i += 1) {
      if (source[i] === '(') depth += 1;
      else if (source[i] === ')') depth -= 1;
      if (depth === 0) {
        found.push(source.slice(start, i + 1));
        break;
      }
    }
  }
  return found;
}

it('never hands a CSS cubicBezier() easing to a shared-value or layout animation', () => {
  // easeOut/easeInOut are CSS-transition objects; withTiming and layout builders need
  // timingEaseOut (Easing.bezier). Mixing them crashed the UI thread on device.
  const offenders = sources().filter(([, text]) =>
    /easing:\s*ease(Out|InOut)\b|\.easing\(\s*ease(Out|InOut)\s*\)/.test(text),
  );
  expect(offenders.map(([path]) => path)).toEqual([]);
});

it('keeps easing objects out of every worklet body', () => {
  const WORKLET = /useAnimated(Style|Props|ScrollHandler|Reaction)\(/g;
  const EASING = /\b(easeOut|easeInOut|timingEaseOut|cubicBezier|Easing)\b/;
  const offenders = sources().flatMap(([path, text]) =>
    calls(text, WORKLET)
      .filter((body) => EASING.test(body))
      .map(() => path),
  );
  expect(offenders).toEqual([]);
});

it('finds the worklets it guards (the scan is not vacuous)', () => {
  const count = sources().reduce(
    (n, [, text]) => n + calls(text, /useAnimated(Style|Props)\(/g).length,
    0,
  );
  expect(count).toBeGreaterThan(5);
});
