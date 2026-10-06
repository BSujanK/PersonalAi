// Drafts placed in the chat composer by "Reply", "Ask agent about this", and the Files actions.
// They only name what the agent needs to find the item (account, message or file id, path); the
// owner reads and edits the draft before sending, and anything the agent then proposes to send or
// share still waits for a biometric approval.
import type { CalendarEvent, Deadline, DigestItem, FileHit, MailMessage } from './api';

type MailRef = Pick<MailMessage, 'account' | 'id' | 'subject'> & { fromLabel: string };

export function mailRef(mail: MailMessage | DigestItem): MailRef {
  const from = 'from' in mail ? mail.from.name || mail.from.addr : mail.from_name || mail.from_addr;
  return { account: mail.account, id: mail.id, subject: mail.subject, fromLabel: from };
}

const quote = (text: string) => `"${text.replace(/\s+/g, ' ').trim() || '(no subject)'}"`;

export function askAboutMail(m: MailRef): string {
  return `About the email from ${m.fromLabel} with subject ${quote(m.subject)} (account ${m.account}, message id ${m.id}): `;
}

export function replyToMail(m: MailRef): string {
  return `Draft a reply to the email from ${m.fromLabel} with subject ${quote(m.subject)} (account ${m.account}, message id ${m.id}). Say: `;
}

export function askAboutDeadline(d: Deadline): string {
  const due = d.due ? `, due ${d.due}` : '';
  const course = d.course ? ` for ${d.course}` : '';
  return `About the deadline ${quote(String(d.title ?? ''))}${course}${due}: `;
}

export function askAboutEvent(e: CalendarEvent): string {
  const when = e.start ? ` on ${e.start}` : '';
  return `About the calendar event ${quote(String(e.summary ?? ''))}${when}: `;
}

function fileRef(file: FileHit): string {
  return file.source === 'local'
    ? `the local file ${file.path}`
    : `the Google Drive file ${quote(file.name)} (account ${file.account}, file id ${file.id})`;
}

export function sendFileByMail(file: FileHit): string {
  return `Email ${fileRef(file)} as an attachment to `;
}

export function shareFileLink(file: FileHit): string {
  return file.source === 'local'
    ? `Upload ${fileRef(file)} to my Google Drive, then create a view-only link to it that anyone with the link can open.`
    : `Create a view-only link to ${fileRef(file)} that anyone with the link can open.`;
}
