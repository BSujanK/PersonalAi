import { fireEvent, render, screen } from '@testing-library/react-native';

import MailDetail from '../../../app/mail/[account]/[id]';
import { getMailMessage, type MailMessage } from '../../lib/api';

const mockNavigate = jest.fn();
jest.mock('expo-router', () => ({
  useLocalSearchParams: () => ({ account: 'student@example.com', id: 'm1' }),
  useRouter: () => ({ back: jest.fn(), navigate: mockNavigate }),
  useNavigation: () => ({}),
}));
jest.mock('../../lib/api', () => ({
  ...jest.requireActual('../../lib/api'),
  getMailMessage: jest.fn(),
}));

jest.setTimeout(30_000);

const BODY =
  'Hello <b>there</b>, see https://example.com/page for details. <img src="https://example.com/t.png">';

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

type Node = { type: string; children: (Node | string)[] | null } | Node[] | string | null;

/** Every host component type in the rendered tree (Image would mean remote content). */
function hostTypes(node: Node): string[] {
  if (node === null || typeof node === 'string') return [];
  if (Array.isArray(node)) return node.flatMap(hostTypes);
  return [node.type, ...(node.children ?? []).flatMap(hostTypes)];
}

beforeEach(() => {
  jest.mocked(getMailMessage).mockReset();
  mockNavigate.mockReset();
});

describe('MailDetail', () => {
  it('shows the header, recipients, date, attachments and the body as plain text', async () => {
    jest.mocked(getMailMessage).mockResolvedValue(mail());
    await render(<MailDetail />);
    expect(await screen.findByText('Project meeting')).toBeTruthy();
    expect(getMailMessage).toHaveBeenCalledWith('student@example.com', 'm1');
    expect(screen.getByText('Asha Rao')).toBeTruthy();
    expect(screen.getByText('asha@example.com')).toBeTruthy();
    expect(screen.getByText('AR')).toBeTruthy();
    expect(screen.getByText(/student@example\.com$/)).toBeTruthy();
    expect(screen.getByText(/Ravi <ravi@example\.com>/)).toBeTruthy();
    expect(screen.getByText('important · from your advisor')).toBeTruthy();
    expect(screen.getByText('INBOX')).toBeTruthy();
    expect(screen.getByText('1 attachment')).toBeTruthy();
    expect(screen.getByText('notes.pdf')).toBeTruthy();
    expect(screen.getByText('2 KB · application/pdf')).toBeTruthy();
    // The markup, the URL and the image tag are shown verbatim, never interpreted or fetched.
    const body = screen.getByText(BODY);
    expect(body.props.selectable).toBe(true);
    expect(body.props.dataDetectorType).toBeUndefined();
    expect(hostTypes(screen.toJSON())).not.toContain('Image');
    expect(screen.queryByText(/saved copy/)).toBeNull();
  });

  it('Reply and Ask agent open a new chat with a draft naming this message', async () => {
    jest.mocked(getMailMessage).mockResolvedValue(mail());
    await render(<MailDetail />);
    await screen.findByText('Project meeting');

    await fireEvent.press(screen.getByLabelText('Reply'));
    let call = mockNavigate.mock.calls[0][0] as { pathname: string; params: { d: string } };
    expect(call.pathname).toBe('/');
    expect(call.params.d).toContain('Draft a reply to the email from Asha Rao');
    expect(call.params.d).toContain('"Project meeting"');
    expect(call.params.d).toContain('message id m1');

    await fireEvent.press(screen.getByLabelText('Ask agent about this'));
    call = mockNavigate.mock.calls[1][0] as { pathname: string; params: { d: string } };
    expect(call.params.d).toMatch(/^About the email from Asha Rao/);
    expect(call.params.d).toContain('account student@example.com');
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
