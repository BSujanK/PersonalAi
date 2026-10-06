import { act, fireEvent, render, screen } from '@testing-library/react-native';

import Today from '../../../app/today';
import {
  ApiError,
  getAccounts,
  getDeadlines,
  getToday,
  type Today as TodayDigest,
  type TodaySection,
  type UpcomingDeadline,
} from '../../lib/api';
import { emitRefresh } from '../../lib/refreshBus';

const mockPush = jest.fn();
const mockNavigate = jest.fn();
const mockNavigation = { addListener: () => () => undefined };
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: mockPush, navigate: mockNavigate, back: jest.fn() }),
  useLocalSearchParams: () => ({}),
  useNavigation: () => mockNavigation,
  useFocusEffect: (effect: () => void | (() => void)) => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    require('react').useEffect(effect, []);
  },
}));
jest.mock('../../lib/api', () => ({
  ...jest.requireActual('../../lib/api'),
  getToday: jest.fn(),
  getDeadlines: jest.fn(),
  getAccounts: jest.fn(),
}));

jest.setTimeout(30_000);

const MAIL: TodayDigest = {
  generated_at: '2026-10-06T08:00:00Z',
  mail: {
    important: [
      {
        account: 'student@example.com',
        id: 'm1',
        from_name: 'Asha Rao',
        from_addr: 'asha@example.com',
        subject: 'Project meeting',
        snippet: 'Moved to Friday',
        reason: 'from your advisor',
        received: '2026-10-06T07:00:00Z',
      },
    ],
    counts: {},
    unclassified: 0,
  },
};

const DEADLINE: UpcomingDeadline = {
  id: 7,
  kind: 'assignment',
  title: 'Assignment 3',
  due: '2026-10-09',
  source: 'classroom',
  source_account: 'student@example.com',
  source_id: 'c1',
  calendar_added: true,
  status: 'active',
};

/** getToday answers per section; a section mapped to an Error fails. */
function answer(by: Partial<Record<TodaySection, TodayDigest | Error>>) {
  jest.mocked(getToday).mockImplementation(async (sections) => {
    const result = by[sections?.[0] ?? 'mail'];
    if (result instanceof Error) throw result;
    return result ?? { generated_at: 'x' };
  });
}

beforeEach(() => {
  mockPush.mockReset();
  mockNavigate.mockReset();
  jest.mocked(getToday).mockReset();
  jest.mocked(getDeadlines).mockReset();
  jest.mocked(getDeadlines).mockResolvedValue({ items: [DEADLINE] });
  jest.mocked(getAccounts).mockResolvedValue({ accounts: [] });
});

describe('Today', () => {
  it('shows the title and every section header at once, with skeletons while loading', async () => {
    jest.mocked(getToday).mockReturnValue(new Promise(() => undefined));
    jest.mocked(getDeadlines).mockReturnValue(new Promise(() => undefined));
    await render(<Today />);
    expect(screen.getAllByText('Today').length).toBeGreaterThan(0);
    expect(screen.getByText('Important mail')).toBeTruthy();
    expect(screen.getByText('Deadlines')).toBeTruthy();
    expect(screen.getByText('Events')).toBeTruthy();
    expect(screen.getAllByLabelText('Loading')).toHaveLength(3);
  });

  it('asks for each section on its own', async () => {
    answer({ mail: MAIL, events: { generated_at: 'x', events: [] } });
    await render(<Today />);
    expect(getToday).toHaveBeenCalledWith(['mail']);
    expect(getToday).toHaveBeenCalledWith(['events']);
    expect(getDeadlines).toHaveBeenCalledWith(7);
  });

  it('shows the mail when events fail, with a quiet failure card for events', async () => {
    answer({ mail: MAIL, events: new Error('calendar down') });
    await render(<Today />);
    expect(await screen.findByText('Project meeting')).toBeTruthy();
    expect(await screen.findByText("Couldn't load events")).toBeTruthy();
    expect(screen.getByText('Retrying automatically…')).toBeTruthy();
    expect(screen.getByText('calendar down')).toBeTruthy();
    // The other sections are unaffected, and nothing is blank or spinning.
    expect(screen.getByText('Assignment 3')).toBeTruthy();
    expect(screen.queryAllByLabelText('Loading')).toHaveLength(0);
    expect(screen.queryByText("Couldn't load important mail")).toBeNull();
  });

  it('tells "not configured" from "failed just now" by the unavailable list', async () => {
    jest.mocked(getDeadlines).mockRejectedValue(new ApiError(404, 'not found'));
    jest
      .mocked(getToday)
      .mockImplementation(async (sections) =>
        sections?.[0] === 'deadlines'
          ? { generated_at: 'x', deadlines: null }
          : sections?.[0] === 'events'
            ? { generated_at: 'x', events: null, unavailable: ['calendar_events'] }
            : { generated_at: 'x', mail: null },
      );
    await render(<Today />);
    // Mail and deadlines are null and not failing; events are null but listed as unavailable.
    expect(await screen.findByText("Couldn't load events")).toBeTruthy();
    expect(screen.getAllByText('Not configured on the laptop yet.')).toHaveLength(2);
  });

  it('opens the deadline screen from a deadline row', async () => {
    answer({ mail: MAIL, events: { generated_at: 'x', events: [] } });
    await render(<Today />);
    await fireEvent.press(await screen.findByText('Assignment 3'));
    expect(mockPush).toHaveBeenCalledWith({ pathname: '/deadline/[id]', params: { id: '7' } });
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it('falls back to the digest deadlines only when /deadlines is missing (404)', async () => {
    jest.mocked(getDeadlines).mockRejectedValue(new ApiError(404, 'not found'));
    jest.mocked(getToday).mockImplementation(async (sections) =>
      sections?.[0] === 'deadlines'
        ? {
            generated_at: 'x',
            deadlines: [{ course: 'Algorithms', title: 'Problem set', due: '2026-10-09' }],
          }
        : { generated_at: 'x', mail: { important: [], counts: {}, unclassified: 0 }, events: [] },
    );
    await render(<Today />);
    await fireEvent.press(await screen.findByText('Problem set'));
    expect(getToday).toHaveBeenCalledWith(['deadlines']);
    expect(mockNavigate.mock.calls[0][0].params.d).toContain('About the deadline "Problem set"');
    expect(mockPush).not.toHaveBeenCalled();
  });

  it('does not use the digest for deadlines when /deadlines merely fails', async () => {
    jest.mocked(getDeadlines).mockRejectedValue(new Error('offline'));
    answer({ mail: MAIL, events: { generated_at: 'x', events: [] } });
    await render(<Today />);
    expect(await screen.findByText("Couldn't load deadlines")).toBeTruthy();
    expect(getToday).not.toHaveBeenCalledWith(['deadlines']);
  });

  it('events still ask the agent', async () => {
    answer({
      mail: MAIL,
      events: {
        generated_at: 'x',
        events: [{ id: 'e1', summary: 'Lecture', start: '2026-10-06T10:00:00Z' }],
      },
    });
    await render(<Today />);
    await fireEvent.press(await screen.findByText('Lecture'));
    expect(mockNavigate.mock.calls[0][0].params.d).toContain('About the calendar event "Lecture"');
  });

  it('keeps showing earlier data, with a note, when a refresh fails', async () => {
    answer({ mail: MAIL, events: { generated_at: 'x', events: [] } });
    await render(<Today />);
    await screen.findByText('Project meeting');
    jest.mocked(getDeadlines).mockRejectedValue(new Error('offline'));
    answer({ mail: new Error('offline'), events: { generated_at: 'x', events: [] } });
    await act(async () => {
      emitRefresh();
    });
    // Mail and deadlines each say so; events refreshed fine.
    expect(await screen.findAllByText('Showing earlier data · retrying')).toHaveLength(2);
    expect(screen.getByText('Project meeting')).toBeTruthy();
  });
});
