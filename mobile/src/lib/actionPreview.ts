// Reads the structure back out of the server's preview text for mail_send, mail_reply,
// drive_upload and drive_share (server/agent/outbound/*_tools.py), so the approval card can show
// recipients with NEW/EXTERNAL badges, attachments and the link scope as real UI.
//
// This is presentation only. The approval card always shows the exact preview text as well, the
// signature covers the server's payload hash, and nothing here decides what gets sent. Parsing
// stops at the "Body:" line, so text inside a mail body can never pose as a recipient row.

export type RecipientField = 'To' | 'Cc' | 'Bcc' | 'People';

export interface PreviewRecipient {
  field: RecipientField;
  addr: string;
  you: boolean;
  /** Never seen in the owner's sent mail. */
  isNew: boolean;
  /** Outside the owner's own domains. */
  external: boolean;
}

export interface PreviewAttachment {
  name: string;
  size: string;
  mime: string | null;
  source: 'local' | 'drive';
  /** Local path, or "Drive of <account>". */
  location: string;
}

export interface ParsedPreview {
  kind: 'mail' | 'drive_upload' | 'drive_share' | 'other';
  account: string | null;
  subject: string | null;
  inReplyTo: string | null;
  recipients: PreviewRecipient[];
  attachments: PreviewAttachment[];
  /** drive_share: the file being shared. */
  file: { name: string; detail: string } | null;
  /** drive_share: "Viewer", "Commenter" or "Editor". */
  access: string | null;
  /** drive_share: whether a public link is created. */
  linkScope: 'anyone' | 'restricted' | null;
  /** drive_upload: destination folder. */
  folder: string | null;
}

const KINDS: Record<string, ParsedPreview['kind']> = {
  mail_send: 'mail',
  mail_reply: 'mail',
  drive_upload: 'drive_upload',
  drive_share: 'drive_share',
};

const FIELDS: RecipientField[] = ['To', 'Cc', 'Bcc', 'People'];
const BULLET = /^ {2}• (.+)$/;

function empty(kind: ParsedPreview['kind']): ParsedPreview {
  return {
    kind,
    account: null,
    subject: null,
    inReplyTo: null,
    recipients: [],
    attachments: [],
    file: null,
    access: null,
    linkScope: null,
    folder: null,
  };
}

function recipient(field: RecipientField, line: string): PreviewRecipient | null {
  // "addr  flags" with two spaces; addresses never contain spaces.
  const cut = line.indexOf('  ');
  const addr = (cut < 0 ? line : line.slice(0, cut)).trim();
  if (!addr.includes('@')) return null;
  const flags = cut < 0 ? '' : line.slice(cut + 2);
  const you = flags.includes('(you)');
  return {
    field,
    addr,
    you,
    isNew: !you && /\bNEW\b/.test(flags),
    external: !you && /\bEXTERNAL\b/.test(flags),
  };
}

// Sizes come from the server's human_size ("240.0 KB") and MIME types have no spaces, so the
// fields can be found even when a file name or path itself contains " — ".
const SIZE = String.raw`\d+(?:\.\d+)? (?:B|KB|MB)`;
const ATTACHMENT = new RegExp(
  String.raw`^(.+?) — (${SIZE}) — (\S+) — (local file .+|Google Drive of .+ \(id [^)]+\))$`,
);
const UPLOAD_FILE = new RegExp(String.raw`^(.+?) — (${SIZE}) — (\S+)$`);

function attachment(line: string): PreviewAttachment | null {
  const m = ATTACHMENT.exec(line);
  if (!m) return null;
  const [, name, size, mime, where] = m;
  if (where.startsWith('local file ')) {
    return { name, size, mime, source: 'local', location: where.slice('local file '.length) };
  }
  const drive = /^Google Drive of (.+?) \(id [^)]+\)$/.exec(where);
  return drive ? { name, size, mime, source: 'drive', location: `Drive of ${drive[1]}` } : null;
}

export function parsePreview(toolName: string, preview: string): ParsedPreview {
  const kind = KINDS[toolName] ?? 'other';
  const out = empty(kind);
  if (kind === 'other') return out;

  let section: 'recipients' | 'attachments' | null = null;
  let field: RecipientField = 'To';
  let uploadFile: { name: string; size: string; mime: string } | null = null;

  for (const line of preview.split('\n')) {
    if (line === 'Body:') break; // everything after this is the mail body: untrusted, verbatim

    const bullet = BULLET.exec(line);
    if (bullet) {
      if (section === 'recipients') {
        const r = recipient(field, bullet[1]);
        if (r) out.recipients.push(r);
      } else if (section === 'attachments') {
        const a = attachment(bullet[1]);
        if (a) out.attachments.push(a);
      }
      continue;
    }
    section = null;

    const heading = /^(To|Cc|Bcc|People):(.*)$/.exec(line);
    if (heading && FIELDS.includes(heading[1] as RecipientField)) {
      field = heading[1] as RecipientField;
      section = heading[2].trim() === '' ? 'recipients' : null;
      continue;
    }
    if (/^Attachments \(/.test(line)) {
      section = 'attachments';
      continue;
    }

    let m: RegExpExecArray | null;
    if ((m = /^Send an email from (.+)$/.exec(line)) || (m = /^Reply from (.+)$/.exec(line))) {
      out.account = m[1];
    } else if ((m = /^Account: (.+)$/.exec(line))) {
      out.account = m[1];
    } else if ((m = /^Subject: (.*)$/.exec(line))) {
      out.subject = m[1];
    } else if ((m = /^In reply to: (.*)$/.exec(line))) {
      out.inReplyTo = m[1];
    } else if ((m = /^Access: (\w+)/.exec(line))) {
      out.access = m[1];
    } else if (line.startsWith('Link sharing: ON')) {
      out.linkScope = 'anyone';
    } else if (line.startsWith('Link sharing: off')) {
      out.linkScope = 'restricted';
    } else if ((m = /^To folder: (.+)$/.exec(line))) {
      out.folder = m[1];
    } else if ((m = /^File: (.+)$/.exec(line))) {
      if (kind === 'drive_upload') {
        const u = UPLOAD_FILE.exec(m[1]);
        if (u) uploadFile = { name: u[1], size: u[2], mime: u[3] };
      } else {
        const share = /^(.*) \(([^()]*)\)$/.exec(m[1]);
        out.file = share ? { name: share[1], detail: share[2] } : { name: m[1], detail: '' };
      }
    } else if ((m = /^From: (.+)$/.exec(line)) && uploadFile) {
      out.attachments.push({ ...uploadFile, source: 'local', location: m[1] });
    }
  }
  return out;
}

/** "a NEW and EXTERNAL recipient" style summary for screen readers and the card header. */
export function recipientWarnings(recipients: PreviewRecipient[]): {
  fresh: number;
  external: number;
} {
  return {
    fresh: recipients.filter((r) => r.isNew).length,
    external: recipients.filter((r) => r.external).length,
  };
}
