import { useCallback, useEffect, useRef, useState } from 'react';

import {
  chat,
  chatStream,
  getConversation,
  OfflineError,
  StreamUnsupportedError,
  type ChatReply,
} from './api';
import {
  appendText,
  applyToolEvent,
  beginTurn,
  failTurn,
  finishTurn,
  fromDisplay,
  promptFor,
  resetText,
  stopTurn,
  type ChatMessage,
} from './chatState';
import { errorMessage } from './format';

const FLUSH_MS = 60;

interface Options {
  /** Conversation to open, or null for a new chat. */
  initialId: string | null;
  /** The server accepted a turn and told us the conversation id. */
  onConversation: (id: string) => void;
  /** A turn ended (finished, stopped or failed); the history list may have changed. */
  onTurnEnd: () => void;
}

export interface ChatSession {
  messages: ChatMessage[];
  loading: boolean;
  loadError: string | null;
  busy: boolean;
  send: (text: string) => void;
  stop: () => void;
  /** Ask the same question again as a new turn. */
  retry: (assistantId: string) => void;
  reload: () => void;
}

/** Owns one conversation on screen: loads history, streams turns, stop, retry. */
export function useChatSession({ initialId, onConversation, onTurnEnd }: Options): ChatSession {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(initialId !== null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const conversationId = useRef<string | null>(initialId);
  const abort = useRef<AbortController | null>(null);
  const counter = useRef(0);
  const messagesRef = useRef<ChatMessage[]>([]);
  const callbacks = useRef({ onConversation, onTurnEnd });
  useEffect(() => {
    callbacks.current = { onConversation, onTurnEnd };
  });

  const apply = useCallback((change: (current: ChatMessage[]) => ChatMessage[]) => {
    messagesRef.current = change(messagesRef.current);
    setMessages(messagesRef.current);
  }, []);

  const load = useCallback(
    (id: string) => {
      let cancelled = false;
      setLoading(true);
      setLoadError(null);
      getConversation(id).then(
        (detail) => {
          if (cancelled) return;
          apply(() => detail.messages.map(fromDisplay));
          setLoading(false);
        },
        (e: unknown) => {
          if (cancelled) return;
          setLoadError(errorMessage(e));
          setLoading(false);
        },
      );
      return () => {
        cancelled = true;
      };
    },
    [apply],
  );

  useEffect(() => {
    if (initialId === null) return;
    return load(initialId);
  }, [initialId, load]);

  // Leaving the chat stops listening to a running reply; the agent still finishes and saves it.
  useEffect(
    () => () => {
      abort.current?.abort();
    },
    [],
  );

  const run = useCallback(
    async (text: string) => {
      const userId = `local-u${counter.current++}`;
      const assistantId = `local-a${counter.current++}`;
      apply((current) => beginTurn(current, userId, assistantId, text));
      setBusy(true);
      const controller = new AbortController();
      abort.current = controller;
      // Set once the server has accepted the turn (its first event), so it may already be running.
      let started = false;
      let buffer = '';
      let timer: ReturnType<typeof setTimeout> | undefined;
      const flush = () => {
        clearTimeout(timer);
        timer = undefined;
        if (buffer) {
          const chunk = buffer;
          buffer = '';
          apply((current) => appendText(current, assistantId, chunk));
        }
      };
      const accept = (result: ChatReply) => {
        conversationId.current = result.conversation_id;
        callbacks.current.onConversation(result.conversation_id);
        apply((current) =>
          finishTurn(current, assistantId, result.reply, result.pending_action_ids),
        );
      };
      try {
        const result = await chatStream(
          text,
          conversationId.current,
          {
            onStart: (id) => {
              started = true;
              conversationId.current = id;
              callbacks.current.onConversation(id);
            },
            onToken: (chunk) => {
              started = true;
              buffer += chunk;
              timer ??= setTimeout(flush, FLUSH_MS);
            },
            onReset: () => {
              clearTimeout(timer);
              timer = undefined;
              buffer = '';
              apply((current) => resetText(current, assistantId));
            },
            onTool: (name, status) => {
              started = true;
              flush();
              apply((current) => applyToolEvent(current, assistantId, name, status));
            },
          },
          { signal: controller.signal },
        );
        flush();
        accept(result);
      } catch (e) {
        flush();
        if (e instanceof Error && e.name === 'AbortError') {
          apply((current) => stopTurn(current, assistantId));
        } else if (!started && (e instanceof StreamUnsupportedError || e instanceof OfflineError)) {
          // Fall back to the plain call only when the server never accepted the stream: after
          // that it may already have run the turn, so resending could repeat it.
          try {
            accept(await chat(text, conversationId.current));
          } catch (fallbackError) {
            apply((current) => failTurn(current, assistantId, errorMessage(fallbackError)));
          }
        } else {
          apply((current) => failTurn(current, assistantId, errorMessage(e)));
        }
      } finally {
        clearTimeout(timer);
        if (abort.current === controller) abort.current = null;
        setBusy(false);
        callbacks.current.onTurnEnd();
      }
    },
    [apply],
  );

  const send = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || abort.current) return;
      void run(trimmed);
    },
    [run],
  );

  const stop = useCallback(() => abort.current?.abort(), []);

  const retry = useCallback(
    (assistantId: string) => {
      if (abort.current) return;
      const prompt = promptFor(messagesRef.current, assistantId);
      if (prompt) void run(prompt);
    },
    [run],
  );

  const reload = useCallback(() => {
    if (conversationId.current) load(conversationId.current);
  }, [load]);

  return { messages, loading, loadError, busy, send, stop, retry, reload };
}
