import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import type { ComponentProps } from 'react';
import { Alert } from 'react-native';

import { deleteConversation, listConversations, renameConversation } from '../../../lib/api';
import { ConversationsProvider } from '../../../lib/Conversations';
import { AppDrawerContent } from '../DrawerContent';

const mockNavigate = jest.fn();
jest.mock('expo-router', () => ({ useRouter: () => ({ navigate: mockNavigate }) }));
jest.mock('../../../lib/AgentStatus', () => ({
  useAgentStatus: () => ({ online: true, pendingCount: 3, refresh: jest.fn() }),
}));
jest.mock('../../../lib/api', () => ({
  ...jest.requireActual('../../../lib/api'),
  listConversations: jest.fn(),
  renameConversation: jest.fn(),
  deleteConversation: jest.fn(),
}));

jest.setTimeout(30_000);

const ITEMS = [
  { id: 'c1', title: "What's due this week?", updated_at: 'x', preview: '' },
  { id: 'c2', title: 'Spending in September', updated_at: 'x', preview: '' },
];

type DrawerProps = ComponentProps<typeof AppDrawerContent>;
const closeDrawer = jest.fn();
const props = {
  navigation: { closeDrawer },
  state: { routes: [{ name: 'index' }], index: 0 },
} as unknown as DrawerProps;

async function renderDrawer() {
  await render(
    <ConversationsProvider>
      <AppDrawerContent {...props} />
    </ConversationsProvider>,
  );
  await screen.findByText("What's due this week?");
}

beforeEach(() => {
  mockNavigate.mockClear();
  closeDrawer.mockClear();
  jest.mocked(listConversations).mockReset();
  jest.mocked(renameConversation).mockReset();
  jest.mocked(deleteConversation).mockReset();
  jest.mocked(listConversations).mockResolvedValue({ items: ITEMS, next_cursor: null });
});

describe('AppDrawerContent', () => {
  it('lists recents and the four destinations with the pending badge', async () => {
    await renderDrawer();
    expect(screen.getByText('Spending in September')).toBeTruthy();
    expect(screen.getByText('Recents')).toBeTruthy();
    for (const label of ['Today', 'Money', 'Settings']) {
      expect(screen.getByLabelText(label)).toBeTruthy();
    }
    expect(screen.getByLabelText('Approvals, 3 pending')).toBeTruthy();
  });

  it('opens a conversation, a new chat and the other screens', async () => {
    await renderDrawer();
    await fireEvent.press(screen.getByLabelText('Spending in September'));
    expect(mockNavigate).toHaveBeenLastCalledWith({ pathname: '/', params: { c: 'c2', k: '' } });
    expect(closeDrawer).toHaveBeenCalled();

    await fireEvent.press(screen.getByLabelText('New chat'));
    const call = mockNavigate.mock.calls[mockNavigate.mock.calls.length - 1][0] as {
      pathname: string;
      params: { c: string; k: string };
    };
    expect(call.pathname).toBe('/');
    expect(call.params.c).toBe('');
    expect(call.params.k).not.toBe('');

    await fireEvent.press(screen.getByLabelText('Approvals, 3 pending'));
    expect(mockNavigate).toHaveBeenLastCalledWith('/approvals');
  });

  it('searches titles through the server after a short pause', async () => {
    await renderDrawer();
    jest.mocked(listConversations).mockResolvedValue({ items: [ITEMS[1]], next_cursor: null });
    await fireEvent.changeText(screen.getByLabelText('Search conversations'), 'spend');
    await waitFor(() =>
      expect(listConversations).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'spend' })),
    );
    expect(await screen.findByText('Results')).toBeTruthy();
    await waitFor(() => expect(screen.queryByText("What's due this week?")).toBeNull());
  });

  it('long-press opens the menu and rename saves the new title', async () => {
    jest.mocked(renameConversation).mockResolvedValue({ ...ITEMS[1], title: 'September budget' });
    await renderDrawer();
    await fireEvent(screen.getByLabelText('Spending in September'), 'longPress');
    await fireEvent.press(await screen.findByLabelText('Rename'));
    const field = await screen.findByLabelText('Chat title');
    await fireEvent.changeText(field, '  September budget ');
    await fireEvent.press(screen.getByText('Save'));
    await waitFor(() => expect(renameConversation).toHaveBeenCalledWith('c2', 'September budget'));
    expect(await screen.findByText('September budget')).toBeTruthy();
  });

  it('delete asks first, then removes the conversation', async () => {
    const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
    jest.mocked(deleteConversation).mockResolvedValue({});
    await renderDrawer();
    await fireEvent(screen.getByLabelText("What's due this week?"), 'longPress');
    await fireEvent.press(await screen.findByLabelText('Delete'));
    expect(deleteConversation).not.toHaveBeenCalled(); // nothing is deleted before confirming
    const buttons = alert.mock.calls[0][2] ?? [];
    const confirm = buttons.find((b) => b.style === 'destructive');
    await act(async () => {
      confirm?.onPress?.();
    });
    await waitFor(() => expect(deleteConversation).toHaveBeenCalledWith('c1'));
    await waitFor(() => expect(screen.queryByText("What's due this week?")).toBeNull());
  });
});
