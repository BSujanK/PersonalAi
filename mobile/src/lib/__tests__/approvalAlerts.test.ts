import * as Notifications from 'expo-notifications';
import { AppState } from 'react-native';

import { listApprovals, type Approval } from '../api';
import { outcomeForResponse } from '../alerts';
import { approvalNoticeBody, notifyNewApprovals } from '../approvalAlerts';
import { loadSeenApprovals, rememberApprovals, unseenApprovals } from '../approvalSeen';

jest.mock('expo-notifications', () => ({
  getPermissionsAsync: jest.fn(),
  scheduleNotificationAsync: jest.fn(),
  setNotificationChannelAsync: jest.fn(),
  setNotificationCategoryAsync: jest.fn(),
  AndroidImportance: { HIGH: 4 },
}));
jest.mock('../api', () => ({ ...jest.requireActual('../api'), listApprovals: jest.fn() }));

const mockStore = new Map<string, string>();
jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn(async (key: string) => mockStore.get(key) ?? null),
  setItemAsync: jest.fn(async (key: string, value: string) => {
    mockStore.set(key, value);
  }),
}));

function pending(...ids: string[]): Approval[] {
  return ids.map((id) => ({
    id,
    tool_name: 'mail_send',
    // Content that must never reach a notification.
    preview: 'Send "Salary offer" to friend@example.com\n\nThe account number is 000111222',
    payload_hash: 'h',
    nonce: 'n',
    status: 'pending',
    created_at: '2026-10-07T10:00:00Z',
    expires_at: '2026-10-07T10:15:00Z',
  }));
}

const appState = AppState as { currentState: string };
const original = appState.currentState;
const inState = (state: 'active' | 'background') => {
  appState.currentState = state;
};

beforeEach(() => {
  mockStore.clear();
  jest.clearAllMocks();
  jest.mocked(Notifications.getPermissionsAsync).mockResolvedValue({ status: 'granted' } as never);
});
afterEach(() => {
  appState.currentState = original;
});

describe('approval notice text', () => {
  it('is only a count', () => {
    expect(approvalNoticeBody(1)).toBe('1 action waiting for approval');
    expect(approvalNoticeBody(3)).toBe('3 actions waiting for approval');
  });

  it('finds the ids not seen yet', () => {
    expect(unseenApprovals(['a', 'b', 'c'], ['b'])).toEqual(['a', 'c']);
    expect(unseenApprovals([], ['b'])).toEqual([]);
  });
});

describe('notifyNewApprovals', () => {
  it('fires a content-free notice for a new pending action while in the background', async () => {
    inState('background');
    await rememberApprovals(['old']);
    jest.mocked(listApprovals).mockResolvedValue(pending('old', 'new1'));
    await notifyNewApprovals();
    expect(Notifications.scheduleNotificationAsync).toHaveBeenCalledTimes(1);
    const request = jest.mocked(Notifications.scheduleNotificationAsync).mock.calls[0][0];
    expect(request.content.body).toBe('1 action waiting for approval');
    const everything = JSON.stringify(request);
    for (const secret of ['Salary', 'friend@example.com', '000111222', 'mail_send', 'new1']) {
      expect(everything).not.toContain(secret);
    }
    expect(request.content.data).toMatchObject({ target: { type: 'approvals' } });
  });

  it('opens the Approvals tab when the notice is tapped', () => {
    const data = { alertId: 0, target: { type: 'approvals' } };
    expect(outcomeForResponse('expo.modules.notifications.actions.DEFAULT', data)).toEqual({
      type: 'route',
      route: { pathname: '/approvals' },
    });
  });

  it('announces an action only once', async () => {
    inState('background');
    await rememberApprovals([]);
    jest.mocked(listApprovals).mockResolvedValue(pending('a1'));
    await notifyNewApprovals();
    await notifyNewApprovals();
    expect(Notifications.scheduleNotificationAsync).toHaveBeenCalledTimes(1);
    expect(await loadSeenApprovals()).toEqual(['a1']);
  });

  it('does nothing in the foreground, so the app shows it instead', async () => {
    inState('active');
    await rememberApprovals([]);
    jest.mocked(listApprovals).mockResolvedValue(pending('a1'));
    await notifyNewApprovals();
    expect(listApprovals).not.toHaveBeenCalled();
    expect(Notifications.scheduleNotificationAsync).not.toHaveBeenCalled();
  });

  it('records on the first run without a notice, and stays quiet without permission', async () => {
    inState('background');
    jest.mocked(listApprovals).mockResolvedValue(pending('a1'));
    await notifyNewApprovals();
    expect(Notifications.scheduleNotificationAsync).not.toHaveBeenCalled();
    expect(await loadSeenApprovals()).toEqual(['a1']);

    jest.mocked(listApprovals).mockResolvedValue(pending('a1', 'a2'));
    jest.mocked(Notifications.getPermissionsAsync).mockResolvedValue({ status: 'denied' } as never);
    await notifyNewApprovals();
    expect(Notifications.scheduleNotificationAsync).not.toHaveBeenCalled();
  });
});
