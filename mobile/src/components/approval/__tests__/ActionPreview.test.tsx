import { render, screen, within } from '@testing-library/react-native';

import { previewVectors } from '../../../test/previewVectors';
import { ActionPreview } from '../ActionPreview';

jest.setTimeout(30_000);

const V = previewVectors();

describe('ActionPreview', () => {
  it('badges NEW and EXTERNAL recipients and lists attachments with size and source', async () => {
    await render(<ActionPreview toolName="mail_send" preview={V.mail_send.preview} />);
    expect(screen.getByText('recruiter@example.org')).toBeTruthy();
    // recruiter is NEW and EXTERNAL, new.person is NEW only, asha has neither, me is "you".
    expect(screen.getAllByText('NEW')).toHaveLength(2);
    expect(screen.getAllByText('EXTERNAL')).toHaveLength(1);
    expect(screen.getAllByText('YOU')).toHaveLength(1);
    expect(screen.getAllByLabelText('new: you have never emailed this address')).toHaveLength(2);
    expect(screen.getByLabelText('external: outside your own domains')).toBeTruthy();
    expect(screen.getByText('Bcc')).toBeTruthy();

    expect(screen.getByText('cv — final.pdf')).toBeTruthy();
    expect(screen.getAllByText('240.0 KB · application/pdf')).toHaveLength(1);
    expect(screen.getByText('Laptop: C:\\Users\\owner\\Documents\\cv — final.pdf')).toBeTruthy();
    expect(screen.getByText('Drive of me@example.com')).toBeTruthy();
  });

  it('always shows the exact preview, body included, as selectable text', async () => {
    await render(<ActionPreview toolName="mail_send" preview={V.mail_send.preview} />);
    const exact = screen.getByText(V.mail_send.preview);
    expect(exact.props.selectable).toBe(true);
    // The fake recipient inside the body appears only inside the exact text, never as a row.
    expect(screen.queryByText('evil@example.net')).toBeNull();
  });

  it('warns in red about an anyone-with-the-link share', async () => {
    await render(<ActionPreview toolName="drive_share" preview={V.share_anyone.preview} />);
    const alert = screen.getByRole('alert');
    expect(within(alert).getByText('Anyone with the link can open this file')).toBeTruthy();
    expect(screen.getByLabelText('Link scope: anyone with the link')).toBeTruthy();
    expect(screen.getByText('Shared with')).toBeTruthy();
    expect(screen.getByText('Viewer')).toBeTruthy();
  });

  it('shows a restricted share without the warning', async () => {
    await render(<ActionPreview toolName="drive_share" preview={V.share_restricted.preview} />);
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getByLabelText('Link scope: only the people listed')).toBeTruthy();
  });

  it('shows only the exact text for other tools', async () => {
    await render(<ActionPreview toolName="phone_set_alarm" preview="Set an alarm for 07:00" />);
    expect(screen.getByText('Set an alarm for 07:00')).toBeTruthy();
    expect(screen.queryByText('NEW')).toBeNull();
  });
});
