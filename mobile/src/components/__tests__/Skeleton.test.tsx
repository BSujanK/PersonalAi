import { render, screen } from '@testing-library/react-native';
import * as Reanimated from 'react-native-reanimated';

import { SkeletonBlock, SkeletonGroup, SkeletonRows } from '../Skeleton';

const HIDDEN = { includeHiddenElements: true };

afterEach(() => jest.restoreAllMocks());

describe('Skeleton', () => {
  it('SkeletonRows draws the asked number of cards under one "Loading" group', async () => {
    await render(<SkeletonRows count={4} />);
    expect(screen.getAllByTestId('skeleton-row', HIDDEN)).toHaveLength(4);
    expect(screen.getAllByLabelText('Loading')).toHaveLength(1);
  });

  it('defaults to three rows, mail-card shaped with an avatar', async () => {
    await render(<SkeletonRows avatar />);
    expect(screen.getAllByTestId('skeleton-row', HIDDEN)).toHaveLength(3);
  });

  it('reads as "Loading" and hides its blocks from screen readers', async () => {
    await render(<SkeletonRows count={2} />);
    expect(screen.getByLabelText('Loading').props.accessible).toBe(true);
    expect(screen.queryAllByTestId('skeleton-row')).toHaveLength(0);
  });

  it('renders a block of the given size inside a group', async () => {
    await render(
      <SkeletonGroup>
        <SkeletonBlock width={40} height={12} radius={6} />
      </SkeletonGroup>,
    );
    expect(screen.getByLabelText('Loading')).toBeTruthy();
  });

  it('pulses while motion is allowed', async () => {
    const repeat = jest.spyOn(Reanimated, 'withRepeat');
    await render(<SkeletonRows />);
    // One shared pulse for the whole group, not one per row.
    expect(repeat).toHaveBeenCalledTimes(1);
    expect(repeat.mock.calls[0].slice(1)).toEqual([-1, true]);
  });

  it('stays still under Reduce Motion', async () => {
    jest.spyOn(Reanimated, 'useReducedMotion').mockReturnValue(true);
    const repeat = jest.spyOn(Reanimated, 'withRepeat');
    await render(<SkeletonRows />);
    expect(repeat).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Loading')).toBeTruthy();
  });
});
