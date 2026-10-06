import { act, fireEvent, render, screen } from '@testing-library/react-native';

import Inbox from '../../../app/inbox';
import { getAccounts, getInbox, type InboxItem, type InboxPage } from '../../lib/api';
import { emitRefresh } from '../../lib/refreshBus';

const mockNavigation = { addListener: () => () => undefined };
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn() }),
  useNavigation: () => mockNavigation,
  useFocusEffect: (effect: () => void | (() => void)) => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    require('react').useEffect(effect, []);
  },
}));
jest.mock('../../lib/api', () => ({
  ...jest.requireActual('../../lib/api'),
  getInbox: jest.fn(),
  getAccounts: jest.fn(),
}));

jest.setTimeout(30_000);

const mail = (id: string): InboxItem => ({
  account: 'student@example.com',
  id,
  message_id: id,
  thread_id: `t${id}`,
  category: 'normal',
  from_name: 'Asha Rao',
  from_addr: 'asha@example.com',
  subject: `Subject ${id}`,
  snippet: '',
  reason: null,
  received: '2026-10-06T07:00:00Z',
  unread: false,
});

const page = (ids: string[], next: string | null): InboxPage => ({
  items: ids.map(mail),
  counts: { important: 0, normal: 9, promo: 0, spam: 0, unclassified: 0 },
  next_cursor: next,
});

beforeEach(() => {
  jest.mocked(getInbox).mockReset();
  jest.mocked(getAccounts).mockResolvedValue({ accounts: [] });
});

describe('All mail', () => {
  it('shows skeleton cards, then the mail', async () => {
    let answer: (value: InboxPage) => void = () => undefined;
    jest.mocked(getInbox).mockReturnValue(new Promise((resolve) => (answer = resolve)));
    await render(<Inbox />);
    expect(screen.getByLabelText('Loading')).toBeTruthy();
    await act(async () => answer(page(['a'], null)));
    expect(await screen.findByText('Subject a')).toBeTruthy();
    expect(screen.queryByLabelText('Loading')).toBeNull();
    expect(screen.queryByText('Load more')).toBeNull();
  });

  it('keeps the pages from "Load more" when it refreshes, with the new mail on top', async () => {
    jest.mocked(getInbox).mockResolvedValueOnce(page(['a', 'b'], 'c1'));
    await render(<Inbox />);
    await screen.findByText('Subject a');

    jest.mocked(getInbox).mockResolvedValueOnce(page(['c', 'd'], 'c2'));
    await fireEvent.press(screen.getByText('Load more'));
    expect(getInbox).toHaveBeenLastCalledWith({ cursor: 'c1', limit: 50 });
    await screen.findByText('Subject d');

    // New mail 'z' pushes 'b' off the first page; it stays, and "Load more" continues from c2.
    jest.mocked(getInbox).mockResolvedValueOnce(page(['z', 'a'], 'c1'));
    await act(async () => {
      emitRefresh();
    });
    expect(await screen.findByText('Subject z')).toBeTruthy();
    for (const id of ['a', 'b', 'c', 'd']) expect(screen.getByText(`Subject ${id}`)).toBeTruthy();
    jest.mocked(getInbox).mockResolvedValueOnce(page(['e'], null));
    await fireEvent.press(screen.getByText('Load more'));
    expect(getInbox).toHaveBeenLastCalledWith({ cursor: 'c2', limit: 50 });
    expect(await screen.findByText('Subject e')).toBeTruthy();
    expect(screen.queryByText('Load more')).toBeNull();
  });

  it('keeps showing the mail, with a note, when a refresh fails', async () => {
    jest.mocked(getInbox).mockResolvedValueOnce(page(['a'], null));
    await render(<Inbox />);
    await screen.findByText('Subject a');
    jest.mocked(getInbox).mockRejectedValueOnce(new Error('offline'));
    await act(async () => {
      emitRefresh();
    });
    expect(await screen.findByText('Showing earlier data · retrying')).toBeTruthy();
    expect(screen.getByText('Subject a')).toBeTruthy();
  });
});
