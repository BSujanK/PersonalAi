// The PersonalAi mark: an organic radial "spark". Nine soft petal-shaped rays, each narrow at
// the inside and rounded at the tip, leaning the same way like a pinwheel, around a separate
// small core with a clear gap between core and rays. Lengths and angles are slightly uneven so it
// reads as drawn, not generated.
//
// Pure geometry with no imports: the app draws it with react-native-svg, and
// scripts/render-brand.mjs draws the same paths into the launcher, splash and notification PNGs.

/** Drawing box: 100 x 100, centred on (50, 50). */
export const SPARK_VIEWBOX = 100;
const C = 50;

/** Radius of the core dot, and where the rays start (the gap between them is the core ring). */
export const SPARK_CORE_R = 7;
const RAY_START = 15;

// Per-ray unevenness, fixed so the mark never changes between renders.
// [angle offset in degrees, length, width]
const RAYS: readonly (readonly [number, number, number])[] = [
  [0, 47, 8.6],
  [3, 39, 7.8],
  [-2, 44, 8.2],
  [4, 37, 7.4],
  [-1, 46, 8.6],
  [2, 40, 7.8],
  [-3, 45, 8.2],
  [1, 38, 7.4],
  [-2, 43, 8.2],
];

/** Degrees each ray's tip leans past its base: the pinwheel twist. */
const LEAN = 14;

const round = (n: number) => Math.round(n * 100) / 100;

function polar(r: number, deg: number): [number, number] {
  const a = ((deg - 90) * Math.PI) / 180;
  return [C + r * Math.cos(a), C + r * Math.sin(a)];
}

/** One ray as an SVG path: a narrow base near the core, a full body and a round tip. */
function rayPath(index: number): string {
  const [offset, length, width] = RAYS[index];
  const base = (360 / RAYS.length) * index + offset;
  const [bx, by] = polar(RAY_START, base);
  const [tx, ty] = polar(length, base + LEAN);
  const len = Math.hypot(tx - bx, ty - by);
  const dx = (tx - bx) / len;
  const dy = (ty - by) / len;
  // Normal to the ray's axis.
  const nx = -dy;
  const ny = dx;
  const tipR = width * 0.4;
  // The leading side bulges more than the trailing side, which is what makes it turn.
  const lead = width * 0.62;
  const trail = width * 0.46;
  const p = (x: number, y: number) => `${round(x)} ${round(y)}`;
  const tipL: [number, number] = [tx + nx * tipR - dx * tipR, ty + ny * tipR - dy * tipR];
  const tipT: [number, number] = [tx - nx * tipR - dx * tipR, ty - ny * tipR - dy * tipR];
  return [
    `M${p(bx, by)}`,
    `C${p(bx + dx * len * 0.3 + nx * lead, by + dy * len * 0.3 + ny * lead)} ${p(
      tipL[0] - dx * len * 0.22 + nx * lead * 0.35,
      tipL[1] - dy * len * 0.22 + ny * lead * 0.35,
    )} ${p(tipL[0], tipL[1])}`,
    `A${round(tipR)} ${round(tipR)} 0 0 0 ${p(tipT[0], tipT[1])}`,
    `C${p(
      tipT[0] - dx * len * 0.22 - nx * trail * 0.35,
      tipT[1] - dy * len * 0.22 - ny * trail * 0.35,
    )} ${p(bx + dx * len * 0.3 - nx * trail, by + dy * len * 0.3 - ny * trail)} ${p(bx, by)}`,
    'Z',
  ].join(' ');
}

/** Every ray's path, in drawing order. */
export const SPARK_RAYS: readonly string[] = RAYS.map((_, i) => rayPath(i));

/** Gradient stops, light at the top left to the deep glow at the bottom right. */
export const SPARK_STOPS: readonly (readonly [number, string])[] = [
  [0, '#C4B5FD'],
  [0.5, '#8B5CF6'],
  [1, '#6D28D9'],
];
