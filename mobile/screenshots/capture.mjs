// Captures every screen from the web export, rendered with synthetic data.
//   PERSONALAI_SCREENSHOTS=1 npx expo export -p web --output-dir <dir>
//   node screenshots/capture.mjs <dir> ../docs/ui
// Needs Playwright's Chromium (not an app dependency).
import { createReadStream, existsSync, mkdirSync, statSync } from 'node:fs';
import { createServer } from 'node:http';
import { extname, join } from 'node:path';
// Playwright is a dev tool installed separately, not an app dependency.
// eslint-disable-next-line import/no-unresolved
import { chromium } from 'playwright';

const [root, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });

const TYPES = {
  '.html': 'text/html',
  '.js': 'text/javascript',
  '.ttf': 'font/ttf',
  '.png': 'image/png',
  '.json': 'application/json',
};
const server = createServer((req, res) => {
  const path = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  let file = join(root, path);
  if (!existsSync(file) || statSync(file).isDirectory()) file = join(root, 'index.html');
  res.setHeader('content-type', TYPES[extname(file)] ?? 'application/octet-stream');
  createReadStream(file).pipe(res);
}).listen(0);
const base = `http://127.0.0.1:${server.address().port}`;

// [file, path, schemes, action?]
const SHOTS = [
  ['intro-1-spin', '/', ['dark'], 'intro:300'],
  ['intro-2-glow', '/', ['dark'], 'intro:900'],
  ['intro-3-glide', '/', ['dark'], 'intro:1300'],
  ['chat-home', '/', ['dark', 'light']],
  ['chat-conversation', '/?c=c1', ['dark']],
  ['chat-thinking', '/', ['dark'], 'send'],
  ['more', '/more', ['dark', 'light']],
  ['today', '/today', ['dark', 'light']],
  ['today-loading', '/today?slow', ['dark']],
  ['inbox', '/inbox', ['dark', 'light']],
  ['deadline', '/deadline/1', ['dark', 'light']],
  ['history', '/history', ['dark']],
  ['money', '/money', ['dark', 'light']],
  ['money-transactions', '/money', ['dark'], 'scroll'],
  ['approvals', '/approvals', ['dark', 'light']],
  ['approvals-share', '/approvals', ['dark'], 'scroll'],
  ['approvals-empty', '/approvals?noapprovals', ['dark']],
  ['mail', '/mail/student%40college.example.com/m1', ['dark', 'light']],
  ['files', '/files', ['dark'], 'search'],
  ['alerts', '/alerts', ['dark']],
  ['settings', '/settings', ['dark']],
  ['pairing', '/?unpaired', ['dark', 'light']],
];

const browser = await chromium.launch();
const failures = [];
for (const [name, path, schemes, action] of SHOTS) {
  for (const scheme of schemes) {
    const page = await browser.newPage({
      viewport: { width: 412, height: 892 },
      deviceScaleFactor: 2,
      colorScheme: scheme,
      reducedMotion: 'no-preference',
    });
    page.on('pageerror', (e) => failures.push(`${name}: ${e.message}`));
    await page.goto(base + path);
    if (action?.startsWith('intro:')) {
      // Frames of the cold-launch intro, timed from first paint.
      await page.waitForSelector('[data-testid="launch-intro"]');
      await page.waitForTimeout(Number(action.slice(6)));
    } else {
      await page.waitForTimeout(2400);
    }
    if (action === 'scroll') {
      await page.mouse.move(206, 500);
      await page.mouse.wheel(0, 900);
      await page.waitForTimeout(1200);
    } else if (action === 'send') {
      await page.getByLabel('Message', { exact: true }).fill('Email Ravi the lab notes');
      await page.getByLabel('Send message').click();
      await page.waitForTimeout(900);
    } else if (action === 'search') {
      await page.getByLabel('Search files', { exact: false }).first().fill('lab4');
      await page.waitForTimeout(1500);
    }
    const file = join(out, `${name}-${scheme}.png`);
    await page.screenshot({ path: file });
    console.log(`wrote ${file}`);
    await page.close();
  }
}
await browser.close();
server.close();
if (failures.length) {
  console.error(failures.join('\n'));
  process.exitCode = 1;
}
