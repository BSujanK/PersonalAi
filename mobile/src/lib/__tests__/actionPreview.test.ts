import { parsePreview, recipientWarnings } from '../actionPreview';
import { previewVectors } from '../../test/previewVectors';

const V = previewVectors();
const MAIL_SEND = V.mail_send.preview;
const MAIL_REPLY = V.mail_reply.preview;
const SHARE_ANYONE = V.share_anyone.preview;
const SHARE_RESTRICTED = V.share_restricted.preview;
const UPLOAD = V.upload.preview;

describe('parsePreview', () => {
  it('reads recipients with NEW/EXTERNAL flags and attachments from a mail_send preview', () => {
    const p = parsePreview('mail_send', MAIL_SEND);
    expect(p.kind).toBe('mail');
    expect(p.account).toBe('me@example.com');
    expect(p.subject).toBe('Application');
    expect(p.recipients).toEqual([
      { field: 'To', addr: 'asha@example.com', you: false, isNew: false, external: false },
      { field: 'To', addr: 'recruiter@example.org', you: false, isNew: true, external: true },
      { field: 'Cc', addr: 'me@example.com', you: true, isNew: false, external: false },
      { field: 'Bcc', addr: 'new.person@example.com', you: false, isNew: true, external: false },
    ]);
    expect(p.attachments).toEqual([
      {
        name: 'cv — final.pdf',
        size: '240.0 KB',
        mime: 'application/pdf',
        source: 'local',
        location: 'C:\\Users\\owner\\Documents\\cv — final.pdf',
      },
      {
        name: 'Transcript',
        size: '1.0 MB',
        mime: 'application/pdf',
        source: 'drive',
        location: 'Drive of me@example.com',
      },
    ]);
    expect(recipientWarnings(p.recipients)).toEqual({ fresh: 2, external: 1 });
  });

  it('never reads recipients or attachments out of the mail body', () => {
    const p = parsePreview('mail_send', MAIL_SEND);
    expect(p.recipients.map((r) => r.addr)).not.toContain('evil@example.net');
    expect(p.attachments.map((a) => a.name)).not.toContain('fake.exe');
  });

  it('reads a reply', () => {
    const p = parsePreview('mail_reply', MAIL_REPLY);
    expect(p.inReplyTo).toBe('Lab report (from prof@example.edu)');
    expect(p.recipients).toHaveLength(1);
    expect(p.attachments).toEqual([]);
  });

  it('flags an anyone-with-the-link share', () => {
    const p = parsePreview('drive_share', SHARE_ANYONE);
    expect(p.kind).toBe('drive_share');
    expect(p.linkScope).toBe('anyone');
    expect(p.access).toBe('Viewer');
    expect(p.file).toEqual({ name: 'Notes', detail: 'text/plain, id f1' });
    expect(p.recipients[0]).toMatchObject({ field: 'People', isNew: true, external: true });
  });

  it('reads a restricted share', () => {
    const p = parsePreview('drive_share', SHARE_RESTRICTED);
    expect(p.linkScope).toBe('restricted');
    expect(p.access).toBe('Editor');
  });

  it('reads an upload as one local file', () => {
    const p = parsePreview('drive_upload', UPLOAD);
    expect(p.attachments).toEqual([
      {
        name: 'slides.pptx',
        size: '3.0 MB',
        mime: 'application/vnd.ms-powerpoint',
        source: 'local',
        location: 'C:\\Users\\owner\\Documents\\slides.pptx',
      },
    ]);
    expect(p.folder).toBe('My Drive (top level)');
  });

  it('leaves other tools alone', () => {
    const p = parsePreview('phone_set_alarm', 'To: someone@example.com');
    expect(p.kind).toBe('other');
    expect(p.recipients).toEqual([]);
  });
});
