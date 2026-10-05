// Navigation into the chat screen. `c` is the conversation id (empty for a new chat) and `k` is a
// nonce so choosing "New chat" again still gives a fresh, empty chat.
import type { useRouter } from 'expo-router';

type Router = ReturnType<typeof useRouter>;

export function openNewChat(router: Router): void {
  router.navigate({ pathname: '/', params: { c: '', k: String(Date.now()) } });
}

export function openConversation(router: Router, id: string): void {
  router.navigate({ pathname: '/', params: { c: id, k: '' } });
}
