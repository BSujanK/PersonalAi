import { fireEvent, render, screen } from '@testing-library/react-native';

import { Composer } from '../Composer';
import { EmptyState } from '../EmptyState';
import { SUGGESTIONS } from '../../../lib/greeting';

jest.setTimeout(30_000);

describe('Composer', () => {
  it('sends the trimmed text and clears the box', async () => {
    const onSend = jest.fn();
    await render(<Composer busy={false} online onSend={onSend} onStop={jest.fn()} />);
    expect(screen.getByLabelText('Send message').props.accessibilityState).toMatchObject({
      disabled: true,
    });
    await fireEvent.changeText(screen.getByLabelText('Message'), 'Any important mail?');
    await fireEvent.press(screen.getByLabelText('Send message'));
    expect(onSend).toHaveBeenCalledWith('Any important mail?');
    expect(screen.getByLabelText('Message').props.value).toBe('');
  });

  it('turns into a stop button while a reply streams', async () => {
    const onStop = jest.fn();
    await render(<Composer busy online onSend={jest.fn()} onStop={onStop} />);
    expect(screen.queryByLabelText('Send message')).toBeNull();
    await fireEvent.press(screen.getByLabelText('Stop generating'));
    expect(onStop).toHaveBeenCalled();
  });

  it('is disabled with an indicator while the agent is offline', async () => {
    const onSend = jest.fn();
    await render(<Composer busy={false} online={false} onSend={onSend} onStop={jest.fn()} />);
    expect(screen.getByText(/Agent offline/)).toBeTruthy();
    expect(screen.getByLabelText('Message').props.editable).toBe(false);
    await fireEvent.press(screen.getByLabelText('Send message'));
    expect(onSend).not.toHaveBeenCalled();
  });

  it('says "still working" instead of offline while a turn runs', async () => {
    await render(<Composer busy online={false} onSend={jest.fn()} onStop={jest.fn()} />);
    expect(screen.queryByText(/Agent offline/)).toBeNull();
    expect(screen.getByText(/Still working/)).toBeTruthy();
    expect(screen.getByLabelText('Stop generating')).toBeTruthy();
  });

  it('does not flag offline before the first check finishes', async () => {
    await render(<Composer busy={false} online={null} onSend={jest.fn()} onStop={jest.fn()} />);
    expect(screen.queryByText(/Agent offline/)).toBeNull();
    expect(screen.getByLabelText('Message').props.editable).toBe(true);
  });
});

describe('EmptyState', () => {
  it('greets by time of day and offers the starter suggestions', async () => {
    const onPick = jest.fn();
    await render(<EmptyState onPick={onPick} now={new Date(2026, 9, 6, 19, 30)} />);
    expect(screen.getByText('Good evening')).toBeTruthy();
    for (const { label } of SUGGESTIONS) expect(screen.getByLabelText(label)).toBeTruthy();
    await fireEvent.press(screen.getByLabelText("Today's digest"));
    expect(onPick).toHaveBeenCalledWith(
      "Give me today's digest: important mail, deadlines and today's events.",
    );
  });

  it.each(SUGGESTIONS)('the $label chip sends its full request', async ({ label, prompt }) => {
    const onPick = jest.fn();
    await render(<EmptyState onPick={onPick} now={new Date(2026, 9, 6, 8, 0)} />);
    await fireEvent.press(screen.getByLabelText(label));
    expect(onPick).toHaveBeenCalledTimes(1);
    expect(onPick).toHaveBeenCalledWith(prompt);
    expect(prompt.endsWith('.') || prompt.endsWith('?')).toBe(true);
  });

  it('ignores taps while disabled', async () => {
    const onPick = jest.fn();
    await render(<EmptyState onPick={onPick} disabled now={new Date(2026, 9, 6, 8, 0)} />);
    expect(screen.getByText('Good morning')).toBeTruthy();
    await fireEvent.press(screen.getByLabelText('Emails'));
    expect(onPick).not.toHaveBeenCalled();
  });

  it('opens Today from the digest chip; the other chips ask the agent', async () => {
    const onPick = jest.fn();
    const onOpen = jest.fn();
    await render(<EmptyState onPick={onPick} onOpen={onOpen} />);
    await fireEvent.press(screen.getByLabelText("Today's digest"));
    expect(onOpen).toHaveBeenCalledWith('today');
    await fireEvent.press(screen.getByLabelText('News'));
    expect(onPick).toHaveBeenCalledWith(SUGGESTIONS.find((s) => s.label === 'News')?.prompt);
  });

  it('is a greeting and the chips only: no amount, no cards', async () => {
    await render(<EmptyState onPick={jest.fn()} />);
    expect(screen.queryByText(/₹/)).toBeNull();
    expect(screen.queryByText('Spent today')).toBeNull();
    expect(screen.queryByLabelText(/^Mail,/)).toBeNull();
  });
});
