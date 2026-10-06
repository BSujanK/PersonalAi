import { useLocalSearchParams } from 'expo-router';

import { ChatView } from '../../src/components/chat/ChatView';

const first = (value: string | string[] | undefined): string =>
  (Array.isArray(value) ? value[0] : value) ?? '';

/**
 * `c` is the conversation to open (empty for a new chat); `k` is a nonce that forces a fresh
 * chat when "New chat" is chosen again; `d` prefills the composer. The key remounts the view, so
 * each chat has its own state.
 */
export default function ChatScreen() {
  const params = useLocalSearchParams<{ c?: string; k?: string; d?: string }>();
  const id = first(params.c) || null;
  return (
    <ChatView
      key={`${id ?? 'new'}:${first(params.k)}`}
      conversationId={id}
      draft={first(params.d)}
    />
  );
}
