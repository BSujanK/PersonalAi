import { fireEvent, render, screen } from '@testing-library/react-native';

import MailDetail from '../../../app/mail/[account]/[id]';
import { ApiError, getMailMessage, getMailSummary, type MailMessage } from '../../lib/api';

const mockNavigate = jest.fn();
const mockNavigation = { addListener: () => () => undefined };
const mockParams = { account: 'student@example.com', id: 'm1' };
jest.mock('expo-router', () => ({
  useLocalSearchParams: () => mockParams,
  useRouter: () => ({ back: jest.fn(), navigate: mockNavigate }),
  useNavigation: () => mockNavigation,
  useFocusEffect: (effect: () => void | (() => void)) => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    require('react').useEffect(effect, []);
  },
}));
jest.mock('../../lib/api', () => ({
  ...jest.requireActual('../../lib/api'),
  getMailMessage: jest.fn(),
  getMailSummary: jest.fn(),
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

const SUMMARY = {
  summary: {
    text: 'The nightly build failed on main.',
    points: ['Two tests are red', 'Last green build was Monday'],
    actions: [
      { text: 'Fix the flaky test', due: '2026-10-17' },
      { text: 'Reply to Ravi', due: null },
    ],
  },
  cached: false,
  model: 'm',
};

beforeEach(() => {
  jest.mocked(getMailMessage).mockReset();
  // By default the summary is unavailable, so the screen shows the plain mail.
  jest.mocked(getMailSummary).mockReset();
  jest.mocked(getMailSummary).mockRejectedValue(new ApiError(503, 'summary_unavailable'));
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
    const body = await screen.findByText(BODY);
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
    expect(getMailSummary).toHaveBeenCalledWith('student@example.com', 'm1');
  });

  describe('summary', () => {
    it('shows the summary first and the original after one tap', async () => {
      jest.mocked(getMailMessage).mockResolvedValue(mail());
      jest.mocked(getMailSummary).mockResolvedValue(SUMMARY);
      await render(<MailDetail />);

      const text = await screen.findByText('The nightly build failed on main.');
      expect(text.props.selectable).toBe(true);
      expect(screen.getByText('Summary').props.accessibilityRole).toBe('header');
      expect(screen.getByText('by agent')).toBeTruthy();
      expect(screen.getByText('Two tests are red')).toBeTruthy();
      expect(screen.getByText('Last green build was Monday')).toBeTruthy();
      expect(screen.getByText('To do').props.accessibilityRole).toBe('header');
      expect(screen.getByText('Fix the flaky test')).toBeTruthy();
      expect(screen.getByText(/^Due .*Sat.*17.*Oct|^Due .*Sat.*Oct.*17/)).toBeTruthy();
      expect(screen.getByText('Reply to Ravi')).toBeTruthy();
      expect(screen.queryByText(BODY)).toBeNull();
      expect(screen.queryByText(/Plain text only/)).toBeNull();
      // Attachments belong to the mail, not the body, so they stay in view.
      expect(screen.getByText('notes.pdf')).toBeTruthy();

      const show = screen.getByRole('button', { name: 'Show full email' });
      expect(show.props.accessibilityState).toMatchObject({ expanded: false });
      await fireEvent.press(show);
      expect((await screen.findByText(BODY)).props.selectable).toBe(true);
      expect(screen.getByText(/Plain text only/)).toBeTruthy();
      const hide = screen.getByRole('button', { name: 'Hide full email' });
      expect(hide.props.accessibilityState).toMatchObject({ expanded: true });
      expect(screen.getByText('The nightly build failed on main.')).toBeTruthy();

      await fireEvent.press(hide);
      expect(screen.queryByText(BODY)).toBeNull();
      expect(screen.getByRole('button', { name: 'Show full email' })).toBeTruthy();
    });

    it('hides the sections that came back empty', async () => {
      jest.mocked(getMailMessage).mockResolvedValue(mail());
      jest.mocked(getMailSummary).mockResolvedValue({
        ...SUMMARY,
        summary: { text: 'Just a note.', points: [], actions: [] },
      });
      await render(<MailDetail />);
      await screen.findByText('Just a note.');
      expect(screen.queryByText('To do')).toBeNull();
    });

    it('asks for the summary beside the mail, not after it', async () => {
      jest.mocked(getMailMessage).mockReturnValue(new Promise(() => undefined));
      jest.mocked(getMailSummary).mockReturnValue(new Promise(() => undefined));
      await render(<MailDetail />);
      expect(getMailMessage).toHaveBeenCalledWith('student@example.com', 'm1');
      expect(getMailSummary).toHaveBeenCalledWith('student@example.com', 'm1');
    });

    it('shows skeleton lines and the original one tap away while it loads', async () => {
      jest.mocked(getMailMessage).mockResolvedValue(mail());
      jest.mocked(getMailSummary).mockReturnValue(new Promise(() => undefined));
      await render(<MailDetail />);
      expect(await screen.findByText('Summarising…')).toBeTruthy();
      expect(screen.getByText('Summary')).toBeTruthy();
      expect(screen.getByLabelText('Loading')).toBeTruthy();
      expect(screen.queryByText(BODY)).toBeNull();
      await fireEvent.press(screen.getByRole('button', { name: 'Show full email' }));
      expect(await screen.findByText(BODY)).toBeTruthy();
    });

    it('falls back to the full body, with no banner and no toggle, when it fails', async () => {
      jest.mocked(getMailMessage).mockResolvedValue(mail());
      for (const error of [new ApiError(503, 'summary_unavailable'), new Error('network down')]) {
        jest.mocked(getMailSummary).mockRejectedValue(error);
        const view = await render(<MailDetail />);
        expect(await screen.findByText(BODY)).toBeTruthy();
        expect(screen.queryByText('Summary')).toBeNull();
        expect(screen.queryByText('Summarising…')).toBeNull();
        expect(screen.queryByText(/full email/)).toBeNull();
        expect(screen.queryByText(/network down|unavailable/)).toBeNull();
        await view.unmount();
      }
    });

    it('still asks for the summary when the mail comes from the saved copy', async () => {
      jest.mocked(getMailMessage).mockResolvedValue(mail({ source: 'stored' }));
      jest.mocked(getMailSummary).mockResolvedValue(SUMMARY);
      await render(<MailDetail />);
      expect(await screen.findByText('The nightly build failed on main.')).toBeTruthy();
      expect(screen.getByText('Showing the saved copy; Gmail could not be reached.')).toBeTruthy();
    });
  });

  it('shows an error when the mail cannot be loaded', async () => {
    jest.mocked(getMailMessage).mockRejectedValue(new Error('network down'));
    await render(<MailDetail />);
    expect(await screen.findByText('network down')).toBeTruthy();
  });
});
