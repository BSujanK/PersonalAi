import { act, fireEvent, render, screen } from '@testing-library/react-native';
import { useEffect } from 'react';
import { Text, View } from 'react-native';

import { IntroProvider, resetIntroForTests, useIntro } from '../brand/LaunchIntro';
import { Spark, type SparkState } from '../brand/Spark';

function Probe() {
  const { active } = useIntro();
  return <Text>{active ? 'intro playing' : 'intro done'}</Text>;
}

beforeEach(() => {
  jest.useFakeTimers();
  resetIntroForTests();
});
afterEach(() => jest.useRealTimers());

describe('LaunchIntro', () => {
  it('plays once on a cold launch and hands over when it lands', async () => {
    await render(
      <IntroProvider>
        <Probe />
      </IntroProvider>,
    );
    expect(screen.getByText('intro playing')).toBeTruthy();
    expect(screen.getByTestId('launch-intro')).toBeTruthy();
    // Bounded: well under two seconds from launch to Chat.
    await act(async () => {
      jest.advanceTimersByTime(1600);
    });
    expect(screen.getByText('intro done')).toBeTruthy();
    expect(screen.queryByTestId('launch-intro')).toBeNull();
  });

  it('never replays on a warm start (same JS runtime)', async () => {
    const view = await render(
      <IntroProvider key="first">
        <Probe />
      </IntroProvider>,
    );
    // The provider is mounted again (activity recreated) in the same runtime.
    await view.rerender(
      <IntroProvider key="second">
        <Probe />
      </IntroProvider>,
    );
    expect(screen.getByText('intro done')).toBeTruthy();
    expect(screen.queryByTestId('launch-intro')).toBeNull();
  });

  it('a tap skips it at once', async () => {
    await render(
      <IntroProvider>
        <Probe />
      </IntroProvider>,
    );
    await fireEvent.press(screen.getByTestId('launch-intro'));
    await act(async () => {
      jest.advanceTimersByTime(200);
    });
    expect(screen.getByText('intro done')).toBeTruthy();
  });

  it('takes the header mark position and still lands on time', async () => {
    function Header() {
      const { setTarget } = useIntro();
      useEffect(() => setTarget(300, 40, 34), [setTarget]);
      return null;
    }
    await render(
      <IntroProvider>
        <Header />
        <Probe />
      </IntroProvider>,
    );
    await act(async () => {
      jest.advanceTimersByTime(1600);
    });
    expect(screen.getByText('intro done')).toBeTruthy();
  });
});

describe('Spark', () => {
  it.each<SparkState>(['still', 'idle', 'thinking', 'intro'])(
    'renders the %s state',
    async (state) => {
      await render(
        <View testID="mark">
          <Spark size={40} state={state} />
        </View>,
      );
      expect(screen.getByTestId('mark')).toBeTruthy();
    },
  );

  it('settles from thinking back to still without throwing', async () => {
    const view = await render(<Spark size={40} state="thinking" />);
    await view.rerender(<Spark size={40} state="still" />);
    await view.rerender(<Spark size={40} state="idle" />);
    await act(async () => {
      jest.advanceTimersByTime(3000);
    });
    expect(() => view.unmount()).not.toThrow();
  });
});
