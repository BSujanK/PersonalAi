import { act, render, screen } from '@testing-library/react-native';

import { StreamingText } from '../StreamingText';

beforeEach(() => jest.useFakeTimers());
afterEach(() => jest.useRealTimers());

const frames = (n: number) =>
  act(async () => {
    jest.advanceTimersByTime(16 * n);
  });

describe('StreamingText', () => {
  it('shows a finished reply whole, as Markdown, with no reveal', async () => {
    await render(<StreamingText text={'**Done.**\n\n- one'} streaming={false} />);
    expect(screen.queryByTestId('stream-tail')).toBeNull();
    expect(screen.getByText('Done.')).toBeTruthy();
    expect(screen.getByText('one')).toBeTruthy();
  });

  it('reveals a live reply word by word, settled blocks as Markdown and the tail as text', async () => {
    const view = await render(<StreamingText text="" streaming />);
    await view.rerender(<StreamingText text={'**Bold** start.\n\nStill writ'} streaming />);
    // Nothing is shown before the first frame.
    expect(screen.queryByText('Still ')).toBeNull();
    await frames(120);
    // The finished paragraph is Markdown (the asterisks are gone)...
    expect(screen.getByText('Bold')).toBeTruthy();
    // ...and the open paragraph is plain words, markers and all.
    expect(screen.getByTestId('stream-tail').props.accessibilityLabel).toBe('Still writ');
  });

  it('becomes plain Markdown once the stream ends and the reveal catches up', async () => {
    const view = await render(<StreamingText text="" streaming />);
    await view.rerender(<StreamingText text="Almost *there*" streaming />);
    await frames(5);
    await view.rerender(<StreamingText text="Almost *there*" streaming={false} />);
    await frames(120);
    expect(screen.queryByTestId('stream-tail')).toBeNull();
    expect(screen.getByText('there')).toBeTruthy();
  });
});
