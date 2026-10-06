// Pacing for the assistant's streamed reply. Tokens arrive in bursts; the screen reveals them at
// a steady rate in whole words, speeding up when the backlog grows so it never lags far behind.
// Completed Markdown blocks are rendered as Markdown; only the open tail is plain text, so a
// half-written list or code fence never flickers between layouts.

/** Base reveal speed, characters per second, for a small backlog (a calm reading pace). */
export const BASE_CPS = 60;
/** Extra speed per character of backlog: a backlog of 300 chars clears in about a quarter second. */
export const CATCH_UP_PER_CHAR = 12;
/** Never more than this far behind, whatever arrives at once. */
export const MAX_LAG_CHARS = 600;

const FENCE = /^\s{0,3}(```|~~~)/;

/**
 * Split text into a settled part (whole Markdown blocks, ending at a blank line outside any code
 * fence) and the open tail still being written.
 */
export function splitSettled(text: string): { settled: string; tail: string } {
  let inFence = false;
  let boundary = 0;
  let offset = 0;
  const lines = text.split('\n');
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    if (FENCE.test(line)) inFence = !inFence;
    const end = offset + line.length; // index of this line's "\n" (or text end)
    // A blank line outside a fence closes the block above it, but only once the line after it
    // has started (so the boundary itself is final).
    if (!inFence && line.trim() === '' && i > 0 && i < lines.length - 1) boundary = end + 1;
    offset = end + 1;
  }
  return { settled: text.slice(0, boundary), tail: text.slice(boundary) };
}

/**
 * How many characters to show after `elapsedMs`, starting from `shown`, with `text` received so
 * far. Advances at least one character, then on to the end of the current word, so words appear
 * whole.
 */
export function nextRevealLength(shown: number, text: string, elapsedMs: number): number {
  const target = text.length;
  if (shown >= target) return target;
  const backlog = target - shown;
  if (backlog > MAX_LAG_CHARS) return target - MAX_LAG_CHARS;
  const rate = BASE_CPS + backlog * CATCH_UP_PER_CHAR;
  let next = Math.min(target, shown + Math.max(1, Math.round((rate * elapsedMs) / 1000)));
  // Finish the word: reveal up to the next whitespace (or the end of what has arrived).
  while (next < target && !/\s/.test(text[next])) next += 1;
  return next;
}

/** Words of plain tail text, each with its start offset (a stable key) and trailing spaces. */
export function tailWords(tail: string, base: number): { key: number; text: string }[] {
  const words: { key: number; text: string }[] = [];
  const pattern = /\n|[^\s\n]+[^\S\n]*|[^\S\n]+/g;
  for (let m = pattern.exec(tail); m; m = pattern.exec(tail)) {
    words.push({ key: base + m.index, text: m[0] });
  }
  return words;
}
