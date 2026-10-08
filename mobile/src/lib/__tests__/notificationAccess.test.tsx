import { act, renderHook } from '@testing-library/react-native';

import { readNotificationAccess, useNotificationAccess } from '../notificationAccess';

const mockEnabled = jest.fn<boolean, []>();
jest.mock('../../../modules/bank-sms', () => ({
  notificationAccessEnabled: () => mockEnabled(),
  openNotificationAccessSettings: jest.fn(),
}));

// Like the real hook: runs the effect while mounted and again when its callback changes.
jest.mock('expo-router', () => ({
  useNavigation: () => ({ addListener: () => () => undefined }),
  useFocusEffect: (effect: () => void | (() => void)) => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    require('react').useEffect(effect, [effect]);
  },
}));

beforeEach(() => mockEnabled.mockReset());

describe('readNotificationAccess', () => {
  it('returns the native answer', () => {
    expect(readNotificationAccess(() => true)).toBe(true);
    expect(readNotificationAccess(() => false)).toBe(false);
  });

  it('treats a failing native call as off', () => {
    expect(
      readNotificationAccess(() => {
        throw new Error('module missing');
      }),
    ).toBe(false);
  });
});

describe('useNotificationAccess', () => {
  it('reports the current state once the screen is focused', async () => {
    mockEnabled.mockReturnValue(false);
    const { result } = await renderHook(() => useNotificationAccess());
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current).toBe(false);
  });
});
