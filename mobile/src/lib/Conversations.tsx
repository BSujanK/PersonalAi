import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import {
  deleteConversation,
  listConversations,
  renameConversation,
  type ConversationSummary,
} from './api';
import { errorMessage } from './format';
import { onRefresh } from './refreshBus';

const PAGE = 30;
const SEARCH_DEBOUNCE_MS = 250;

interface ConversationsState {
  items: ConversationSummary[];
  loading: boolean;
  error: string | null;
  hasMore: boolean;
  query: string;
  setQuery: (query: string) => void;
  loadMore: () => void;
  refresh: () => void;
  /** The conversation open in the chat screen, for highlighting in the drawer. */
  activeId: string | null;
  setActiveId: (id: string | null) => void;
  rename: (id: string, title: string) => Promise<void>;
  remove: (id: string) => Promise<void>;
}

const noop = () => undefined;
const ConversationsContext = createContext<ConversationsState>({
  items: [],
  loading: false,
  error: null,
  hasMore: false,
  query: '',
  setQuery: noop,
  loadMore: noop,
  refresh: noop,
  activeId: null,
  setActiveId: noop,
  rename: async () => undefined,
  remove: async () => undefined,
});

export function ConversationsProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ConversationSummary[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [activeId, setActiveId] = useState<string | null>(null);
  const generation = useRef(0);

  const loadFirst = useCallback(async (q: string) => {
    const mine = ++generation.current;
    setLoading(true);
    try {
      const page = await listConversations({ limit: PAGE, q });
      if (mine !== generation.current) return;
      setItems(page.items);
      setCursor(page.next_cursor);
      setError(null);
    } catch (e) {
      if (mine === generation.current) setError(errorMessage(e));
    } finally {
      if (mine === generation.current) setLoading(false);
    }
  }, []);

  const loadMore = useCallback(() => {
    if (!cursor || loading) return;
    const mine = generation.current;
    setLoading(true);
    listConversations({ limit: PAGE, cursor, q: query }).then(
      (page) => {
        if (mine !== generation.current) return;
        setItems((current) => {
          const seen = new Set(current.map((c) => c.id));
          return [...current, ...page.items.filter((c) => !seen.has(c.id))];
        });
        setCursor(page.next_cursor);
        setLoading(false);
      },
      (e: unknown) => {
        if (mine !== generation.current) return;
        setError(errorMessage(e));
        setLoading(false);
      },
    );
  }, [cursor, loading, query]);

  // First load, and a new search after the owner pauses typing.
  useEffect(() => {
    const timer = setTimeout(() => void loadFirst(query), query === '' ? 0 : SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query, loadFirst]);

  useEffect(() => onRefresh(() => void loadFirst(query)), [query, loadFirst]);

  const rename = useCallback(async (id: string, title: string) => {
    const updated = await renameConversation(id, title);
    setItems((current) => current.map((c) => (c.id === id ? { ...c, title: updated.title } : c)));
  }, []);

  const remove = useCallback(async (id: string) => {
    await deleteConversation(id);
    setItems((current) => current.filter((c) => c.id !== id));
  }, []);

  const value = useMemo<ConversationsState>(
    () => ({
      items,
      loading,
      error,
      hasMore: cursor !== null,
      query,
      setQuery,
      loadMore,
      refresh: () => void loadFirst(query),
      activeId,
      setActiveId,
      rename,
      remove,
    }),
    [items, loading, error, cursor, query, loadMore, loadFirst, activeId, rename, remove],
  );
  return <ConversationsContext.Provider value={value}>{children}</ConversationsContext.Provider>;
}

export const useConversations = () => useContext(ConversationsContext);
