// Renders the spark mark into every bitmap Android needs: launcher icon, adaptive icon layers,
// the monochrome (themed) icon, the splash image and the notification small icon.
//
// The geometry is the same module the app draws with (src/components/brand/sparkGeometry.ts).
// Needs Node 22+ and Playwright's Chromium (not an app dependency):
//   node --experimental-strip-types scripts/render-brand.mjs
import { chromium } from 'playwright';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import {
  SPARK_CORE_R,
  SPARK_RAYS,
  SPARK_STOPS,
} from '../src/components/brand/sparkGeometry.ts';

const ASSETS = join(dirname(fileURLToPath(import.meta.url)), '..', 'assets');
const INK = '#07060B';
const GLOW = '#2A1260';

const stops = SPARK_STOPS.map(([o, c]) => `<stop offset="${o}" stop-color="${c}"/>`).join('');

/** The mark at `scale` of the canvas, centred. `fill` overrides the gradient (e.g. white). */
function mark(scale, fill) {
  const paint = fill ?? 'url(#spark)';
  const offset = (100 - 100 * scale) / 2;
  return `<g transform="translate(${offset} ${offset}) scale(${scale})">${SPARK_RAYS.map(
    (d) => `<path d="${d}" fill="${paint}"/>`,
  ).join('')}<circle cx="50" cy="50" r="${SPARK_CORE_R}" fill="${paint}"/></g>`;
}

const background = `<rect width="100" height="100" fill="url(#bg)"/>`;

function svg(size, body) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 100 100">
  <defs>
    <linearGradient id="spark" gradientUnits="userSpaceOnUse" x1="10" y1="5" x2="90" y2="95">${stops}</linearGradient>
    <radialGradient id="bg" cx="50%" cy="30%" r="80%">
      <stop offset="0" stop-color="${GLOW}"/><stop offset="1" stop-color="${INK}"/>
    </radialGradient>
  </defs>${body}</svg>`;
}

// Adaptive icons are masked to the centre ~66%; the mark stays inside that safe zone.
const OUTPUTS = [
  ['icon.png', 1024, background + mark(0.66)],
  ['adaptive-icon.png', 1024, mark(0.5)],
  ['adaptive-icon-background.png', 1024, background],
  ['adaptive-icon-monochrome.png', 1024, mark(0.5, '#FFFFFF')],
  ['splash-icon.png', 1024, mark(0.9)],
  // Android tints the small icon itself; it must be white on transparent.
  ['notification-icon.png', 96, mark(0.92, '#FFFFFF')],
];

const browser = await chromium.launch();
const page = await browser.newPage();
for (const [name, size, body] of OUTPUTS) {
  await page.setViewportSize({ width: size, height: size });
  await page.setContent(
    `<html><body style="margin:0;background:transparent">${svg(size, body)}</body></html>`,
  );
  await page.locator('svg').screenshot({ path: join(ASSETS, name), omitBackground: true });
  console.log(`wrote assets/${name} (${size}x${size})`);
}
await browser.close();
