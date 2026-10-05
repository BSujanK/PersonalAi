// Sender-ID hygiene for the bank SMS allowlist. Mirrors SmsFilter.normalise/isValidName in the
// native module: only DLT-style alphanumeric headers (e.g. HDFCBK) are allowed, never a phone
// number, so a malicious server or a typo cannot make the phone queue personal or OTP senders.

const PREFIX = /^[A-Z]{2}-/;
const SUFFIX = /-[STPG]$/;
const NAME = /^[A-Z0-9]{3,11}$/;
const MAX_SENDERS = 200;

export function normaliseSender(sender: string): string {
  return sender.trim().toUpperCase().replace(PREFIX, '').replace(SUFFIX, '');
}

export function isValidSenderName(name: string): boolean {
  return NAME.test(name) && (name.match(/[A-Z]/g) ?? []).length >= 2;
}

/** Keep only well-formed, de-duplicated sender names (normalised), capped at 200 entries. */
export function sanitiseSenders(list: unknown): string[] {
  if (!Array.isArray(list)) return [];
  const out = new Set<string>();
  for (const item of list) {
    if (typeof item !== 'string') continue;
    const name = normaliseSender(item);
    if (isValidSenderName(name)) out.add(name);
    if (out.size >= MAX_SENDERS) break;
  }
  return [...out];
}
