// The phone only ever talks to the laptop over Tailscale (CLAUDE.md rule 5), so it refuses
// any server URL that is not a Tailscale address or a MagicDNS (*.ts.net) name. This also
// stops a forged pairing QR from pointing the app, and its bank SMS, at another host.

const TAILSCALE_SUFFIX = '.ts.net';
const PAIR_CODE = /^[A-Za-z0-9_-]{1,256}$/;

function isTailscaleV4(host: string): boolean {
  const parts = host.split('.');
  if (parts.length !== 4) return false;
  const octets = parts.map((p) => (/^(0|[1-9][0-9]{0,2})$/.test(p) ? Number(p) : NaN));
  if (octets.some((o) => Number.isNaN(o) || o > 255)) return false;
  // 100.64.0.0/10: first octet 100, second octet 64..127.
  return octets[0] === 100 && octets[1] >= 64 && octets[1] <= 127;
}

function isTailscaleV6(addr: string): boolean {
  // fd7a:115c:a1e0::/48: the first three hextets must be exactly these.
  if (!/^fd7a:115c:a1e0(:|$)/.test(addr)) return false;
  if ((addr.match(/::/g) ?? []).length > 1) return false;
  const groups = addr.split(':');
  if (groups.length > 8) return false;
  return groups.every((g) => /^[0-9a-f]{0,4}$/.test(g));
}

function isMagicDns(host: string): boolean {
  return (
    host.endsWith(TAILSCALE_SUFFIX) &&
    host.length > TAILSCALE_SUFFIX.length &&
    /^[a-z0-9.-]+$/.test(host) &&
    !host.includes('..')
  );
}

/** `host` is a bare name, IPv4 address or IPv6 address (without brackets). */
export function isTailscaleHost(host: string): boolean {
  const h = host.toLowerCase();
  return isTailscaleV4(h) || isTailscaleV6(h) || isMagicDns(h);
}

// scheme://host[:port][/], nothing else. Parsed by hand: React Native's URL is incomplete.
const URL_RE = /^(https?):\/\/(\[[0-9A-Fa-f:]+\]|[A-Za-z0-9.-]+)(?::([0-9]{1,5}))?\/?$/;

/** Return the normalised origin (no trailing slash), or throw if the URL is not allowed. */
export function normaliseServerUrl(raw: string): string {
  const match = URL_RE.exec(raw.trim());
  if (!match) {
    throw new Error('server URL must look like http://100.x.y.z:8765 with no path or query');
  }
  const scheme = match[1].toLowerCase();
  const hostPart = match[2].toLowerCase();
  const port = match[3];
  if (port !== undefined && (Number(port) < 1 || Number(port) > 65535)) {
    throw new Error('invalid port');
  }
  const bare = hostPart.startsWith('[') ? hostPart.slice(1, -1) : hostPart;
  const allowed = hostPart.startsWith('[') ? isTailscaleV6(bare) : isTailscaleHost(bare);
  if (!allowed) {
    throw new Error(
      'server must be a Tailscale address (100.64.0.0/10, fd7a:115c:a1e0::/48 or *.ts.net)',
    );
  }
  return `${scheme}://${hostPart}${port !== undefined ? `:${Number(port)}` : ''}`;
}

export interface PairingQr {
  url: string;
  code: string;
}

/** Parse the JSON that `python -m agent pair` encodes in its terminal QR code. */
export function parsePairingQr(data: string): PairingQr {
  let parsed: unknown;
  try {
    parsed = JSON.parse(data);
  } catch {
    throw new Error('not a PersonalAi pairing code');
  }
  if (typeof parsed !== 'object' || parsed === null) {
    throw new Error('not a PersonalAi pairing code');
  }
  const { v, url, code } = parsed as Record<string, unknown>;
  if (v !== 1 || typeof url !== 'string' || typeof code !== 'string' || !PAIR_CODE.test(code)) {
    throw new Error('not a PersonalAi pairing code');
  }
  return { url: normaliseServerUrl(url), code };
}
