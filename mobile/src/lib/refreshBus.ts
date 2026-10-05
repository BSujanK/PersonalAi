// Tiny pub/sub so a push notification, app foregrounding or an approval can refresh every screen.
type Listener = () => void;

const listeners = new Set<Listener>();

export function onRefresh(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function emitRefresh(): void {
  listeners.forEach((listener) => listener());
}
