// Navigation into the chat screen. `c` is the conversation id (empty for a new chat), `k` is a
// nonce so choosing "New chat" again still gives a fresh, empty chat, and `d` is a draft placed
// in the composer. A draft is never sent on its own: the owner reads it, edits it and sends it.
import type { useRouter } from 'expo-router';

type Router = ReturnType<typeof useRouter>;

export function openNewChat(router: Router, draft = ''): void {
  router.navigate({ pathname: '/chat', params: { c: '', k: String(Date.now()), d: draft } });
}

export function openConversation(router: Router, id: string): void {
  router.navigate({ pathname: '/chat', params: { c: id, k: '', d: '' } });
}
