// Web sources the agent used for an answer. They arrive from the server as untrusted wire data
// (`sources` on the chat reply, the SSE `done` event and stored conversation turns), so every
// entry is validated here before it reaches the UI: http(s) only, a real host, at most five.

export interface Source {
  title: string;
  url: string;
}

export const MAX_SOURCES = 5;
const MAX_URL_LENGTH = 2048;
const MAX_TITLE_LENGTH = 200;
const WEB_URL = /^https?:\/\/([^/?#\s@]+)(?:[/?#]\S*)?$/i;

/** The site a URL belongs to, without a port or a leading "www."; null unless it is http(s). */
export function sourceHost(url: string): string | null {
  const match = WEB_URL.exec(url.trim());
  if (!match) return null;
  const host = match[1]
    .replace(/:\d+$/, '')
    .toLowerCase()
    .replace(/^www\./, '');
  return host.includes('.') || host === 'localhost' ? host : null;
}

/** Keep the well-formed entries of an untrusted `sources` value: de-duplicated, capped at five. */
export function parseSources(value: unknown): Source[] {
  if (!Array.isArray(value)) return [];
  const sources: Source[] = [];
  for (const entry of value) {
    if (sources.length >= MAX_SOURCES) break;
    if (typeof entry !== 'object' || entry === null) continue;
    const { url, title } = entry as { url?: unknown; title?: unknown };
    if (typeof url !== 'string') continue;
    const trimmed = url.trim();
    const host = sourceHost(trimmed);
    if (!host || trimmed.length > MAX_URL_LENGTH) continue;
    if (sources.some((s) => s.url === trimmed)) continue;
    const name = typeof title === 'string' ? title.replace(/\s+/g, ' ').trim() : '';
    sources.push({ url: trimmed, title: (name || host).slice(0, MAX_TITLE_LENGTH) });
  }
  return sources;
}

/** A title shortened for a chip, ending in an ellipsis when it was cut. */
export function truncateTitle(title: string, max = 32): string {
  return title.length <= max ? title : `${title.slice(0, max - 1).trimEnd()}…`;
}
