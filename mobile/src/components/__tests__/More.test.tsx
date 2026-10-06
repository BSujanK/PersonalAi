import { fireEvent, render, screen } from '@testing-library/react-native';

import More from '../../../app/more';

const mockPush = jest.fn();
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: mockPush }),
  useNavigation: () => ({}),
}));
jest.mock('../../lib/PairingContext', () => ({
  usePairing: () => ({
    pairing: { deviceId: 'abcdef12-3456-7890', serverUrl: 'http://100.64.0.1:8000' },
    reload: jest.fn(),
  }),
}));
jest.mock('../../lib/AgentStatus', () => ({
  useAgentStatus: () => ({ online: true, pendingCount: 0, refresh: jest.fn() }),
}));

jest.setTimeout(30_000);

beforeEach(() => mockPush.mockReset());

describe('More', () => {
  it('shows the profile card with the device id and agent status', async () => {
    await render(<More />);
    expect(screen.getByText('PersonalAi')).toBeTruthy();
    expect(screen.getByText('Device ABCDEF12')).toBeTruthy();
    expect(screen.getByText('Agent online')).toBeTruthy();
    expect(screen.getByText('Nothing leaves your laptop without your fingerprint.')).toBeTruthy();
  });

  it('lists the tools and the app settings', async () => {
    await render(<More />);
    for (const title of ['Files', 'Alerts', 'Chat history', 'Settings']) {
      expect(screen.getByText(title)).toBeTruthy();
    }
  });

  it('pushes each destination on press', async () => {
    await render(<More />);
    await fireEvent.press(screen.getByText('Files'));
    expect(mockPush).toHaveBeenLastCalledWith('/files');
    await fireEvent.press(screen.getByText('Alerts'));
    expect(mockPush).toHaveBeenLastCalledWith('/alerts');
    await fireEvent.press(screen.getByText('Chat history'));
    expect(mockPush).toHaveBeenLastCalledWith('/history');
    await fireEvent.press(screen.getByText('Settings'));
    expect(mockPush).toHaveBeenLastCalledWith('/settings');
  });
});
