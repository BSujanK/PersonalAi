import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { Linking } from 'react-native';

import DeadlineScreen from '../../../app/deadline/[id]';
import {
  ApiError,
  getAccounts,
  getDeadline,
  undoAutoEvent,
  type DeadlineDetail,
} from '../../lib/api';

const mockPush = jest.fn();
const mockNavigate = jest.fn();
const mockNavigation = { addListener: () => () => undefined };
const mockParams = { id: '7' };
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: mockPush, navigate: mockNavigate, back: jest.fn() }),
  useLocalSearchParams: () => mockParams,
  useNavigation: () => mockNavigation,
  useFocusEffect: (effect: () => void | (() => void)) => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    require('react').useEffect(effect, []);
  },
}));
jest.mock('../../lib/api', () => ({
  ...jest.requireActual('../../lib/api'),
  getDeadline: jest.fn(),
  getAccounts: jest.fn(),
  undoAutoEvent: jest.fn(),
}));

jest.setTimeout(30_000);

const LINK = 'https://www.google.com/calendar/event?eid=ZXhhbXBsZQ';

function deadline(over: Partial<DeadlineDetail> = {}): DeadlineDetail {
  return {
    id: 7,
    kind: 'assignment',
    title: 'Assignment 3',
    due: '2026-10-09T17:00:00Z',
    source: 'mail',
    source_account: 'student@example.com',
    source_id: 'm9',
    message_id: 'm9',
    status: 'active',
    calendar_added: true,
    calendar: { account: 'student@example.com', event_id: 'ev1', link: LINK },
    ...over,
  };
}

beforeEach(() => {
  mockPush.mockReset();
  mockNavigate.mockReset();
  jest.mocked(getDeadline).mockReset();
  jest.mocked(undoAutoEvent).mockReset();
  jest.mocked(getAccounts).mockResolvedValue({ accounts: [] });
  // The RN preset's Linking is already a mock whose calls would carry over between tests.
  jest.spyOn(Linking, 'openURL').mockReset().mockResolvedValue(true);
});
afterEach(() => jest.restoreAllMocks());

describe('Deadline', () => {
  it('shows the title, when it is due and the account it came from', async () => {
    jest.mocked(getDeadline).mockResolvedValue(deadline({ source_label: 'College' }));
    await render(<DeadlineScreen />);
    expect((await screen.findAllByText('Assignment 3')).length).toBeGreaterThan(0);
    expect(getDeadline).toHaveBeenCalledWith(7);
    expect(screen.getByText('College')).toBeTruthy();
    expect(screen.getByText(/2026/)).toBeTruthy();
  });

  it('shows a skeleton while it loads', async () => {
    jest.mocked(getDeadline).mockReturnValue(new Promise(() => undefined));
    await render(<DeadlineScreen />);
    expect(screen.getAllByLabelText('Loading').length).toBeGreaterThan(0);
  });

  it('a mail source opens the mail it came from', async () => {
    jest.mocked(getDeadline).mockResolvedValue(deadline());
    await render(<DeadlineScreen />);
    await fireEvent.press(await screen.findByText('Open the mail it came from'));
    expect(mockPush).toHaveBeenCalledWith({
      pathname: '/mail/[account]/[id]',
      params: { account: 'student@example.com', id: 'm9' },
    });
  });

  it('a Classroom source says so and has no link', async () => {
    jest
      .mocked(getDeadline)
      .mockResolvedValue(deadline({ source: 'classroom', message_id: undefined, course_id: 'c1' }));
    await render(<DeadlineScreen />);
    expect(await screen.findByText('From Google Classroom')).toBeTruthy();
    expect(screen.queryByText('Open the mail it came from')).toBeNull();
  });

  it('opens the calendar event only for a Google Calendar link', async () => {
    jest.mocked(getDeadline).mockResolvedValue(deadline());
    await render(<DeadlineScreen />);
    expect(await screen.findByText('On your calendar')).toBeTruthy();
    await fireEvent.press(screen.getByText('Open in Google Calendar'));
    expect(Linking.openURL).toHaveBeenCalledWith(LINK);
  });

  it.each([
    'https://calendar.google.com/calendar/event?eid=abc',
    'https://www.google.com/calendar/event?eid=abc',
  ])('accepts %s', async (link) => {
    jest
      .mocked(getDeadline)
      .mockResolvedValue(deadline({ calendar: { account: 'a', event_id: 'e', link } }));
    await render(<DeadlineScreen />);
    expect(await screen.findByText('Open in Google Calendar')).toBeTruthy();
  });

  it.each([
    'https://evil.example.com/calendar/event',
    'https://www.google.com.evil.example.com/calendar/',
    'https://www.google.com/maps',
    'http://www.google.com/calendar/event',
    'https://www.google.com/calendar/../url?q=https://evil.example.com',
    'https://www.google.com/calendar/event?eid=abc&continue=https://evil.example.com',
    'javascript:alert(1)',
    '',
  ])('hides the calendar link for %j', async (link) => {
    jest
      .mocked(getDeadline)
      .mockResolvedValue(deadline({ calendar: { account: 'a', event_id: 'e', link } }));
    await render(<DeadlineScreen />);
    expect(await screen.findByText('On your calendar')).toBeTruthy();
    expect(screen.queryByText('Open in Google Calendar')).toBeNull();
    expect(Linking.openURL).not.toHaveBeenCalled();
  });

  it('says when it is not on the calendar and offers no Undo', async () => {
    jest.mocked(getDeadline).mockResolvedValue(deadline({ calendar: null, calendar_added: false }));
    await render(<DeadlineScreen />);
    expect(await screen.findByText('Not on your calendar')).toBeTruthy();
    expect(screen.queryByLabelText('Undo')).toBeNull();
    expect(screen.queryByText('Open in Google Calendar')).toBeNull();
  });

  it('Undo removes the event, confirms and reloads', async () => {
    jest
      .mocked(getDeadline)
      .mockResolvedValueOnce(deadline())
      .mockResolvedValue(deadline({ calendar: null, calendar_added: false }));
    jest.mocked(undoAutoEvent).mockResolvedValue({ status: 'removed' });
    await render(<DeadlineScreen />);
    await fireEvent.press(await screen.findByLabelText('Undo'));
    expect(undoAutoEvent).toHaveBeenCalledWith(7);
    expect(await screen.findByText('Removed from your calendar')).toBeTruthy();
    expect(await screen.findByText('Not on your calendar')).toBeTruthy();
    expect(getDeadline).toHaveBeenCalledTimes(2);
  });

  it('shows the error when Undo fails', async () => {
    jest.mocked(getDeadline).mockResolvedValue(deadline());
    jest.mocked(undoAutoEvent).mockRejectedValue(new Error('network down'));
    await render(<DeadlineScreen />);
    await fireEvent.press(await screen.findByLabelText('Undo'));
    expect(await screen.findByText('network down')).toBeTruthy();
    expect(screen.queryByText('Removed from your calendar')).toBeNull();
  });

  it('"Ask the agent about it" starts a chat draft about the deadline', async () => {
    jest.mocked(getDeadline).mockResolvedValue(deadline());
    await render(<DeadlineScreen />);
    await fireEvent.press(await screen.findByLabelText('Ask the agent about it'));
    const call = mockNavigate.mock.calls[0][0] as { pathname: string; params: { d: string } };
    expect(call.pathname).toBe('/');
    expect(call.params.d).toContain('About the deadline "Assignment 3"');
  });

  it('says so, kindly, when the deadline is no longer tracked (404)', async () => {
    jest.mocked(getDeadline).mockRejectedValue(new ApiError(404, 'not found'));
    await render(<DeadlineScreen />);
    expect(await screen.findByText('This deadline is no longer tracked.')).toBeTruthy();
    expect(screen.queryByText("Couldn't load this deadline")).toBeNull();
  });

  it('shows a quiet failure card, not an error, when the agent cannot be reached', async () => {
    jest.mocked(getDeadline).mockRejectedValue(new Error('offline'));
    await render(<DeadlineScreen />);
    expect(await screen.findByText("Couldn't load this deadline")).toBeTruthy();
    expect(screen.getByText('Retrying automatically…')).toBeTruthy();
    await waitFor(() => expect(screen.queryAllByLabelText('Loading')).toHaveLength(0));
  });
});
