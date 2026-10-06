// A tiny app-wide toast channel: short, content-free confirmations ("Synced 3 bank messages").
// Never put mail, SMS text or amounts in a toast.
type Listener = (message: string) => void;

const listeners = new Set<Listener>();

export function showToast(message: string): void {
  for (const listener of listeners) listener(message);
}

export function onToast(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
