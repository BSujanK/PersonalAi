import { render, screen } from '@testing-library/react-native';

import MailDetail from '../../../app/mail/[account]/[id]';
import { getMailMessage, type MailMessage } from '../../lib/api';

jest.mock('expo-router', () => ({
  useLocalSearchParams: () => ({ account: 'student@example.com', id: 'm1' }),
  useRouter: () => ({ back: jest.fn() }),
  useNavigation: () => ({}),
}));
jest.mock('../../lib/api', () => ({
  ...jest.requireActual('../../lib/api'),
  getMailMessage: jest.fn(),
}));

jest.setTimeout(30_000);

const BODY = 'Hello <b>there</b>, see https://example.com/page for details.';

function mail(over: Partial<MailMessage> = {}): MailMessage {
  return {
    account: 'student@example.com',
    id: 'm1',
    thread_id: 't1',
    from: { name: 'Asha Rao', addr: 'asha@example.com' },
    to: [{ name: '', addr: 'student@example.com' }],
    cc: [{ name: 'Ravi', addr: 'ravi@example.com' }],
    date: '2026-10-05T10:00:00Z',
    subject: 'Project meeting',
    labels: ['INBOX', 'UNREAD'],
    category: 'important',
    reason: 'from your advisor',
    body: BODY,
    body_truncated: false,
    attachments: [{ name: 'notes.pdf', size: 2048, mime: 'application/pdf' }],
    source: 'live',
    ...over,
  };
}

beforeEach(() => jest.mocked(getMailMessage).mockReset());

describe('MailDetail', () => {
  it('shows headers, attachments and the body as plain text', async () => {
    jest.mocked(getMailMessage).mockResolvedValue(mail());
    await render(<MailDetail />);
    expect(await screen.findByText('Project meeting')).toBeTruthy();
    expect(getMailMessage).toHaveBeenCalledWith('student@example.com', 'm1');
    expect(screen.getByText('From: Asha Rao <asha@example.com>')).toBeTruthy();
    expect(screen.getByText('To: student@example.com')).toBeTruthy();
    expect(screen.getByText('Cc: Ravi <ravi@example.com>')).toBeTruthy();
    expect(screen.getByText('important - from your advisor')).toBeTruthy();
    expect(screen.getByText('Labels: INBOX, UNREAD')).toBeTruthy();
    expect(screen.getByText('notes.pdf')).toBeTruthy();
    expect(screen.getByText('2 KB - application/pdf')).toBeTruthy();
    // The markup and URL are shown verbatim, never interpreted.
    const body = screen.getByText(BODY);
    expect(body.props.selectable).toBe(true);
    expect(body.props.dataDetectorType).toBeUndefined();
    expect(screen.queryByText(/saved copy/)).toBeNull();
  });

  it('notes when it is the stored copy and when the body is truncated', async () => {
    jest.mocked(getMailMessage).mockResolvedValue(mail({ source: 'stored', body_truncated: true }));
    await render(<MailDetail />);
    expect(
      await screen.findByText('Showing the saved copy; Gmail could not be reached.'),
    ).toBeTruthy();
    expect(screen.getByText(/only the first part is shown/)).toBeTruthy();
  });

  it('shows an error when the mail cannot be loaded', async () => {
    jest.mocked(getMailMessage).mockRejectedValue(new Error('network down'));
    await render(<MailDetail />);
    expect(await screen.findByText('network down')).toBeTruthy();
  });
});
