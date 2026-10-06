import { fireEvent, render, screen } from '@testing-library/react-native';
import type { BottomTabBarProps } from 'expo-router/js-tabs';
import { StyleSheet } from 'react-native';

import { lightPalette } from '../../theme';

import { FloatingTabBar } from '../nav/FloatingTabBar';

jest.mock('../../lib/AgentStatus', () => ({
  useAgentStatus: () => ({ online: true, pendingCount: 2, refresh: jest.fn() }),
}));
jest.mock('../../lib/haptics', () => ({ haptics: { selection: jest.fn() } }));

const NAMES = ['money', 'index', 'approvals'];
const TITLES = ['Money', 'Chat', 'Approvals'];

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
  it('has exactly Money | Chat | Approvals, Chat active by default, with the badge', async () => {
    await render(<FloatingTabBar {...props(1).props} />);
    const tabs = screen.getAllByRole('tab').map((t) => t.props.accessibilityLabel as string);
    expect(tabs).toEqual(['Money', 'Chat', 'Approvals, 2 pending']);
    expect(screen.getByLabelText('Chat').props.accessibilityState).toEqual({ selected: true });
  });

  it('navigates to another tab and ignores a press on the current one', async () => {
    const { props: p, navigate } = props(1);
    await render(<FloatingTabBar {...p} />);
    await fireEvent.press(screen.getByLabelText('Money'));
    expect(navigate).toHaveBeenCalledWith('money', undefined);
    navigate.mockClear();
    await fireEvent.press(screen.getByLabelText('Chat'));
    expect(navigate).not.toHaveBeenCalled();
  });

  it('sits on an opaque band in the base colour, down to the bottom edge', async () => {
    await render(<FloatingTabBar {...props(1).props} />);
    const band = screen.getByTestId('tab-band');
    const style = StyleSheet.flatten(band.props.style);
    // Tests render without a ThemeProvider, so the default (light) palette applies.
    expect(style.backgroundColor).toBe(lightPalette.bg);
    expect(style.position).toBeUndefined(); // in the layout, not floating over content
    expect(style.paddingBottom).toBeGreaterThan(0);
  });
});
