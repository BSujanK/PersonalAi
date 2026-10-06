import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import Alerts from '../../../app/alerts';
import { getAlertSettings, getNotifications, undoAutoEvent, type AlertItem } from '../../lib/api';

const mockPush = jest.fn();
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: mockPush, back: jest.fn(), canGoBack: () => true }),
  useNavigation: () => ({}),
  useFocusEffect: (effect: () => void | (() => void)) => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    require('react').useEffect(effect, []);
  },
}));
jest.mock('expo-notifications', () => ({
  getPermissionsAsync: jest.fn().mockResolvedValue({ status: 'granted' }),
  requestPermissionsAsync: jest.fn().mockResolvedValue({ status: 'granted' }),
}));
jest.mock('../../lib/api', () => ({
  ...jest.requireActual('../../lib/api'),
  getNotifications: jest.fn(),
  getAlertSettings: jest.fn(),
  putAlertSettings: jest.fn(),
  undoAutoEvent: jest.fn(),
}));

jest.setTimeout(30_000);

const ITEMS: AlertItem[] = [
  {
    id: 1,
    kind: 'important_mail',
    title: 'Mail from Asha Rao',
    body: 'Project meeting moved',
    created_at: '2026-10-05T10:00:00Z',
    target: { type: 'mail', account: 'student@example.com', message_id: 'm1' },
  },
  {
    id: 2,
    kind: 'calendar_added',
    title: 'Assignment 3 due',
    body: 'Added to your calendar',
    created_at: '2026-10-06T08:00:00Z',
    target: { type: 'deadline', deadline_id: 7 },
    actions: ['undo'],
  },
];

beforeEach(() => {
  mockPush.mockReset();
  jest.mocked(undoAutoEvent).mockReset();
  jest.mocked(getNotifications).mockReset();
  jest.mocked(getNotifications).mockResolvedValue({ items: ITEMS, latest_id: 2 });
  jest.mocked(getAlertSettings).mockResolvedValue({
    important_mail: true,
    deadlines: true,
    briefing: false,
    briefing_time: '07:30',
  });
});

describe('Alerts', () => {
  it('lists recent alerts newest first and opens a mail on tap', async () => {
    await render(<Alerts />);
    expect(await screen.findByText('Assignment 3 due')).toBeTruthy();
    expect(screen.getByText('Alert settings')).toBeTruthy();
    await fireEvent.press(screen.getByText('Mail from Asha Rao'));
    expect(mockPush).toHaveBeenCalledWith({
      pathname: '/mail/[account]/[id]',
      params: { account: 'student@example.com', id: 'm1' },
    });
  });

  it('Undo calls undoAutoEvent for the deadline, confirms and reloads', async () => {
    jest.mocked(undoAutoEvent).mockResolvedValue({ status: 'removed' });
    await render(<Alerts />);
    await screen.findByText('Assignment 3 due');
    // Only the auto-added calendar event offers Undo.
    expect(screen.getAllByLabelText('Undo')).toHaveLength(1);
    const loads = jest.mocked(getNotifications).mock.calls.length;

    await fireEvent.press(screen.getByLabelText('Undo'));

    expect(undoAutoEvent).toHaveBeenCalledWith(7);
    expect(await screen.findByText('Removed from your calendar')).toBeTruthy();
    await waitFor(() =>
      expect(jest.mocked(getNotifications).mock.calls.length).toBeGreaterThan(loads),
    );
  });

  it('shows the error when Undo fails', async () => {
    jest.mocked(undoAutoEvent).mockRejectedValue(new Error('network down'));
    await render(<Alerts />);
    await screen.findByText('Assignment 3 due');
    await fireEvent.press(screen.getByLabelText('Undo'));
    expect(await screen.findByText('network down')).toBeTruthy();
    expect(screen.queryByText('Removed from your calendar')).toBeNull();
  });
});
