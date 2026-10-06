import { fireEvent, render, screen } from '@testing-library/react-native';
import type { BottomTabBarProps } from 'expo-router/js-tabs';

import { FloatingTabBar } from '../nav/FloatingTabBar';

jest.mock('../../lib/AgentStatus', () => ({
  useAgentStatus: () => ({ online: true, pendingCount: 2, refresh: jest.fn() }),
}));
jest.mock('../../lib/haptics', () => ({ haptics: { selection: jest.fn() } }));

const NAMES = ['index', 'chat', 'money', 'approvals', 'more'];
const TITLES = ['Home', 'Chat', 'Money', 'Approvals', 'More'];

function props(index: number) {
  const navigate = jest.fn();
  const emit = jest.fn(() => ({ defaultPrevented: false }));
  const routes = NAMES.map((name) => ({ key: `${name}-key`, name, params: undefined }));
  const descriptors = Object.fromEntries(
    routes.map((r, i) => [r.key, { options: { title: TITLES[i] } }]),
  );
  return {
    navigate,
    emit,
    props: {
      state: { index, routes },
      descriptors,
      navigation: { navigate, emit },
      insets: { top: 0, bottom: 0, left: 0, right: 0 },
    } as unknown as BottomTabBarProps,
  };
}

describe('FloatingTabBar', () => {
  it('labels every tab, marks the active one and badges pending approvals', async () => {
    await render(<FloatingTabBar {...props(0).props} />);
    expect(screen.getByLabelText('Home').props.accessibilityState).toEqual({ selected: true });
    for (const label of ['Chat', 'Money', 'More'])
      expect(screen.getByLabelText(label)).toBeTruthy();
    expect(screen.getByLabelText('Approvals, 2 pending')).toBeTruthy();
  });

  it('navigates to another tab and ignores a press on the current one', async () => {
    const { props: p, navigate } = props(0);
    await render(<FloatingTabBar {...p} />);
    await fireEvent.press(screen.getByLabelText('Money'));
    expect(navigate).toHaveBeenCalledWith('money', undefined);
    navigate.mockClear();
    await fireEvent.press(screen.getByLabelText('Home'));
    expect(navigate).not.toHaveBeenCalled();
  });
});
