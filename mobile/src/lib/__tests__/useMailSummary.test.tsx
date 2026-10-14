import { act, renderHook } from '@testing-library/react-native';

import { ApiError, getMailSummary } from '../api';
import { useMailSummary } from '../useMailSummary';

jest.mock('../api', () => ({ ...jest.requireActual('../api'), getMailSummary: jest.fn() }));

const response = (text: string) => ({
  summary: { text, points: [], actions: [] },
  cached: false,
  model: 'm',
});

beforeEach(() => jest.mocked(getMailSummary).mockReset());

describe('useMailSummary', () => {
  it('is loading, then ready with the summary', async () => {
    let answer: (value: ReturnType<typeof response>) => void = () => undefined;
    jest.mocked(getMailSummary).mockReturnValue(new Promise((resolve) => (answer = resolve)));
    const { result } = await renderHook(() => useMailSummary('a@example.com', 'm1'));
    expect(getMailSummary).toHaveBeenCalledWith('a@example.com', 'm1');
    expect(result.current).toEqual({ status: 'loading' });
    await act(async () => answer(response('Hello')));
    expect(result.current).toEqual({ status: 'ready', summary: response('Hello').summary });
  });

  it('fails quietly on any error, without retrying', async () => {
    jest.mocked(getMailSummary).mockRejectedValue(new ApiError(503, 'summary_unavailable'));
    const { result } = await renderHook(() => useMailSummary('a@example.com', 'm1'));
    await act(async () => undefined);
    expect(result.current).toEqual({ status: 'failed' });
    expect(getMailSummary).toHaveBeenCalledTimes(1);
  });

  it('starts over for another mail and drops a late answer for the old one', async () => {
    const answers: Record<string, (value: ReturnType<typeof response>) => void> = {};
    jest
      .mocked(getMailSummary)
      .mockImplementation((_account, id) => new Promise((resolve) => (answers[id] = resolve)));
    const { result, rerender } = await renderHook(
      ({ id }: { id: string }) => useMailSummary('a@example.com', id),
      { initialProps: { id: 'm1' } },
    );
    await rerender({ id: 'm2' });
    expect(result.current).toEqual({ status: 'loading' });
    await act(async () => answers.m1(response('old')));
    expect(result.current).toEqual({ status: 'loading' });
    await act(async () => answers.m2(response('new')));
    expect(result.current).toMatchObject({ status: 'ready', summary: { text: 'new' } });
  });
});
