// Pure state transitions for the chat transcript. The hook in useChatSession.ts drives them.
import type { DisplayMessage, ToolStatus } from './api';
import type { ToolActivity } from './toolLabels';

export type MessageState = 'streaming' | 'done' | 'stopped' | 'error';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  tools: ToolActivity[];
  actionIds: string[];
  state: MessageState;
  error?: string;
}

export function fromDisplay(message: DisplayMessage): ChatMessage {
  return {
    id: message.id,
    role: message.role,
    text: message.text,
    tools: message.tools.map((t) => ({ name: t.name, status: t.status })),
    actionIds: message.pending_action_ids,
    state: 'done',
  };
}

export function update(
  messages: ChatMessage[],
  id: string,
  change: (message: ChatMessage) => ChatMessage,
): ChatMessage[] {
  return messages.map((m) => (m.id === id ? change(m) : m));
}

export function beginTurn(
  messages: ChatMessage[],
  userId: string,
  assistantId: string,
  text: string,
): ChatMessage[] {
  return [
    ...messages,
    { id: userId, role: 'user', text, tools: [], actionIds: [], state: 'done' },
    { id: assistantId, role: 'assistant', text: '', tools: [], actionIds: [], state: 'streaming' },
  ];
}

export const appendText = (messages: ChatMessage[], id: string, chunk: string) =>
  update(messages, id, (m) => ({ ...m, text: m.text + chunk }));

export const resetText = (messages: ChatMessage[], id: string) =>
  update(messages, id, (m) => ({ ...m, text: '' }));

/** A tool began (new entry) or ended (the latest running entry of that name is updated). */
export function applyToolEvent(
  messages: ChatMessage[],
  id: string,
  name: string,
  status: ToolStatus,
): ChatMessage[] {
  return update(messages, id, (m) => {
    if (status === 'started') return { ...m, tools: [...m.tools, { name, status }] };
    const tools = [...m.tools];
    for (let i = tools.length - 1; i >= 0; i--) {
      if (tools[i].name === name && tools[i].status === 'started') {
        tools[i] = { name, status };
        return { ...m, tools };
      }
    }
    return { ...m, tools: [...tools, { name, status }] };
  });
}

export const finishTurn = (
  messages: ChatMessage[],
  id: string,
  reply: string,
  actionIds: string[],
) =>
  update(messages, id, (m) => ({
    ...m,
    text: reply,
    actionIds,
    state: 'done',
    // Anything still marked running when the turn ends finished without a closing event.
    tools: m.tools.map((t) => (t.status === 'started' ? { ...t, status: 'finished' } : t)),
  }));

export const stopTurn = (messages: ChatMessage[], id: string) =>
  update(messages, id, (m) => ({
    ...m,
    state: 'stopped',
    tools: m.tools.map((t) => (t.status === 'started' ? { ...t, status: 'finished' } : t)),
  }));

export const failTurn = (messages: ChatMessage[], id: string, error: string) =>
  update(messages, id, (m) => ({
    ...m,
    state: 'error',
    error,
    tools: m.tools.map((t) => (t.status === 'started' ? { ...t, status: 'failed' } : t)),
  }));

/** The text of the user message that the assistant message `assistantId` answered. */
export function promptFor(messages: ChatMessage[], assistantId: string): string | null {
  const index = messages.findIndex((m) => m.id === assistantId);
  for (let i = index - 1; i >= 0; i--) {
    if (messages[i].role === 'user') return messages[i].text;
  }
  return null;
}
