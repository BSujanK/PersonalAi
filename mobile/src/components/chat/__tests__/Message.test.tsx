import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { Alert, Linking } from 'react-native';

import { getApproval, type Approval } from '../../../lib/api';
import type { ChatMessage } from '../../../lib/chatState';
import { emitRefresh } from '../../../lib/refreshBus';
import { AssistantMessage } from '../Message';

jest.mock('expo-clipboard', () => ({ setStringAsync: jest.fn().mockResolvedValue(true) }));
// The avatar's motion is a native-driven loop; here only whether it is told to think matters.
jest.mock('../../brand/Spark', () => {
  const { createElement } = jest.requireActual('react');
  const { Text } = jest.requireActual('react-native');
  return {
    Spark: () => null,
    SparkAvatar: ({ thinking }: { thinking?: boolean }) =>
      createElement(Text, { testID: 'avatar' }, thinking ? 'thinking' : 'still'),
  };
});
jest.mock('../../../lib/api', () => ({
  ...jest.requireActual('../../../lib/api'),
  getApproval: jest.fn(),
}));
jest.mock('../../../lib/secureKeys', () => ({
  ...jest.requireActual('../../../lib/secureKeys'),
  signWithBiometrics: jest.fn(),
}));
jest.mock('../../../lib/deviceCommands', () => ({ processDeviceCommands: jest.fn() }));

jest.setTimeout(30_000);

const base: ChatMessage = {
  id: 'a1',
  role: 'assistant',
  text: '',
  tools: [],
  actionIds: [],
  sources: [],
  state: 'streaming',
};

const props = { canRetry: false, onRetry: jest.fn() };
const avatar = () => screen.getByTestId('avatar').props.children as string;

describe('thinking state', () => {
  it('shows Thinking beside a thinking avatar, then each tool verb, then collapses into steps', async () => {
    const { rerender } = await render(<AssistantMessage {...props} message={base} />);
    expect(screen.getByText('Thinking…')).toBeTruthy();
    expect(avatar()).toBe('thinking');
    expect(screen.queryByRole('button', { name: /steps/ })).toBeNull();

    const searching: ChatMessage = {
      ...base,
      tools: [{ name: 'web_search', status: 'started' }],
    };
    await rerender(<AssistantMessage {...props} message={searching} />);
    expect(screen.getByText('Searching the web…')).toBeTruthy();
    expect(screen.queryByText('Thinking…')).toBeNull();
    expect(screen.queryByRole('button', { name: /steps/ })).toBeNull();

    const reading: ChatMessage = {
      ...base,
      tools: [
        { name: 'web_search', status: 'finished' },
        { name: 'web_read', status: 'started' },
      ],
    };
    await rerender(<AssistantMessage {...props} message={reading} />);
    expect(screen.getByText('Reading pages…')).toBeTruthy();

    // The first answer text: the status line collapses into the tool steps row above the answer.
    const answering: ChatMessage = { ...reading, text: 'Here is what I found' };
    await rerender(<AssistantMessage {...props} message={answering} />);
    expect(screen.queryByText('Reading pages…', { exact: true })).toBeNull();
    expect(
      screen.getByRole('button', { name: /Reading a web page|Reading web pages/ }),
    ).toBeTruthy();
    expect(avatar()).toBe('thinking');

    // Done: the avatar settles.
    const done: ChatMessage = {
      ...answering,
      state: 'done',
      tools: reading.tools.map((t) => ({ ...t, status: 'finished' as const })),
    };
    await rerender(<AssistantMessage {...props} message={done} />);
    expect(avatar()).toBe('still');
  });

  it('never shows a tool name it does not know, only "Working…"', async () => {
    const message: ChatMessage = {
      ...base,
      tools: [{ name: 'secret_internal_tool', status: 'started' }],
    };
    await render(<AssistantMessage {...props} message={message} />);
    expect(screen.getByText('Working…')).toBeTruthy();
    expect(screen.queryByText(/secret_internal_tool|Secret internal tool/)).toBeNull();
  });

  it('shows no status line for a finished reply loaded from history', async () => {
    const message: ChatMessage = {
      ...base,
      state: 'done',
      text: 'Hello',
      tools: [{ name: 'mail_search', status: 'finished' }],
    };
    await render(<AssistantMessage {...props} message={message} />);
    expect(screen.queryByText('Thinking…')).toBeNull();
    expect(screen.getByRole('button', { name: /Searched mail/ })).toBeTruthy();
    expect(avatar()).toBe('still');
  });
});

describe('Sources row', () => {
  const sources = [
    { title: 'Release notes for the new model', url: 'https://www.example.com/notes' },
    { title: 'A very long headline that goes on and on and on', url: 'https://news.example.org/a' },
  ];
  const done: ChatMessage = { ...base, state: 'done', text: 'Answer', sources };

  it('shows the host and a shortened title per source, and hides when empty', async () => {
    const { rerender } = await render(<AssistantMessage {...props} message={done} />);
    expect(screen.getByText('Sources')).toBeTruthy();
    expect(screen.getByText('example.com')).toBeTruthy();
    expect(screen.getByText('news.example.org')).toBeTruthy();
    expect(screen.queryByText(/goes on and on and on/)).toBeNull(); // truncated
    expect(screen.getByText(/A very long headline that goes…/)).toBeTruthy();

    await rerender(<AssistantMessage {...props} message={{ ...done, sources: [] }} />);
    expect(screen.queryByText('Sources')).toBeNull();
    expect(screen.queryByTestId('sources')).toBeNull();
  });

  it('is not shown while the answer is still streaming', async () => {
    await render(<AssistantMessage {...props} message={{ ...done, state: 'streaming' }} />);
    expect(screen.queryByText('Sources')).toBeNull();
  });

  it('opens a source only through the link confirmation', async () => {
    const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
    const open = jest.spyOn(Linking, 'openURL').mockResolvedValue(true);
    await render(<AssistantMessage {...props} message={done} />);
    await fireEvent.press(screen.getByRole('link', { name: /example\.com, Release notes/ }));
    expect(alert).toHaveBeenCalledTimes(1);
    expect(alert.mock.calls[0][0]).toBe('Open link?');
    expect(alert.mock.calls[0][1]).toBe('https://www.example.com/notes');
    expect(open).not.toHaveBeenCalled();
    // Confirming is the only way through.
    const buttons = alert.mock.calls[0][2] ?? [];
    await act(async () => buttons.find((b) => b.text === 'Open')?.onPress?.());
    expect(open).toHaveBeenCalledWith('https://www.example.com/notes');
  });
});

describe('approvals jump line', () => {
  const ACTION_ID = 'a'.repeat(32);
  const approval = (status: string): Approval => ({
    id: ACTION_ID,
    tool_name: 'phone_reminder',
    preview: 'Remind you on your phone at 2026-10-13T18:00:00+05:30:\nSubmit the lab record',
    payload_hash: 'b'.repeat(64),
    nonce: 'n1',
    status,
    created_at: new Date().toISOString(),
    expires_at: new Date(Date.now() + 600_000).toISOString(),
  });
  const withAction: ChatMessage = { ...base, state: 'done', text: 'Done', actionIds: [ACTION_ID] };

  beforeEach(() => jest.mocked(getApproval).mockReset());

  it('keeps the inline card and adds a line that opens the Approvals tab', async () => {
    jest.mocked(getApproval).mockResolvedValue(approval('pending'));
    const onOpenApprovals = jest.fn();
    await render(
      <AssistantMessage {...props} message={withAction} onOpenApprovals={onOpenApprovals} />,
    );
    expect(await screen.findByLabelText('Approve this action')).toBeTruthy();
    expect(screen.getByText('Set a reminder')).toBeTruthy();
    expect(screen.getByText('Waiting for your approval in Approvals')).toBeTruthy();
    await fireEvent.press(screen.getByLabelText('Open Approvals'));
    expect(onOpenApprovals).toHaveBeenCalledTimes(1);
  });

  it('drops the line once the action is decided elsewhere (the refresh bus reloads the card)', async () => {
    jest.mocked(getApproval).mockResolvedValue(approval('pending'));
    await render(<AssistantMessage {...props} message={withAction} onOpenApprovals={jest.fn()} />);
    expect(await screen.findByText('Waiting for your approval in Approvals')).toBeTruthy();

    jest.mocked(getApproval).mockResolvedValue(approval('executed'));
    await act(async () => emitRefresh());
    await waitFor(() =>
      expect(screen.queryByText('Waiting for your approval in Approvals')).toBeNull(),
    );
    expect(screen.getByText('Approved and done')).toBeTruthy();
  });

  it('shows no line on a reply without actions', async () => {
    await render(
      <AssistantMessage
        {...props}
        message={{ ...base, state: 'done', text: 'Hi' }}
        onOpenApprovals={jest.fn()}
      />,
    );
    expect(screen.queryByText('Waiting for your approval in Approvals')).toBeNull();
  });
});
