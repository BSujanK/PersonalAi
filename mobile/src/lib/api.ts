// Typed client for the laptop agent. Every route except /pair sends the device bearer token.
import { loadPairing } from './secureKeys';
import { createSseParser } from './sse';
import { normaliseServerUrl } from './serverUrl';

const DEFAULT_TIMEOUT_MS = 15_000;
const HEALTH_TIMEOUT_MS = 5_000;
const STREAM_INACTIVITY_MS = 60_000;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(`request failed (${status}): ${detail}`);
    this.name = 'ApiError';
  }
}

/** The agent could not be reached: laptop asleep, Tailscale down, or the request timed out. */
export class OfflineError extends Error {
  constructor() {
    super('the agent is offline');
    this.name = 'OfflineError';
  }
}

/** The agent answered /chat but not with a usable event stream; the plain call may still work. */
export class StreamUnsupportedError extends Error {
  constructor() {
    super('the agent did not stream the reply');
    this.name = 'StreamUnsupportedError';
  }
}

export interface Approval {
  id: string;
  tool_name: string;
  preview: string;
  payload_hash: string;
  nonce: string;
  status: string;
  created_at: string;
  expires_at: string;
}

export interface ToolRun {
  name: string;
  status: 'finished' | 'failed';
}

export type ToolStatus = 'started' | 'finished' | 'failed';

/** One stored conversation, as the history list shows it. */
export interface ConversationSummary {
  id: string;
  title: string;
  updated_at: string;
  preview: string;
}

export interface ConversationPage {
  items: ConversationSummary[];
  next_cursor: string | null;
}

/** A message as the server rehydrates it for this phone: text only, never tool arguments. */
export interface DisplayMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  created_at: string;
  tools: ToolRun[];
  pending_action_ids: string[];
}

export interface ConversationDetail {
  id: string;
  title: string;
  updated_at: string;
  messages: DisplayMessage[];
}

export interface ChatReply {
  conversation_id: string;
  reply: string;
  pending_action_ids: string[];
}

export interface DigestItem {
  account: string;
  id: string;
  from_name: string;
  from_addr: string;
  subject: string;
  snippet: string;
  reason: string | null;
  received: string;
}

export interface MailDigest {
  important: DigestItem[];
  counts: Record<string, number>;
  unclassified: number;
}

export interface CalendarEvent {
  account?: string;
  id?: string;
  summary?: string;
  start?: string;
  end?: string;
  location?: string | null;
}

export interface Deadline {
  account?: string;
  course?: string;
  title?: string;
  due?: string;
}

export interface Today {
  generated_at: string;
  mail: MailDigest | null;
  events: CalendarEvent[] | null;
  deadlines: Deadline[] | null;
}

export const PERIODS = [
  'today',
  'yesterday',
  'this_week',
  'last_week',
  'this_month',
  'last_month',
  'last_7_days',
  'last_30_days',
  'this_year',
] as const;
export type Period = (typeof PERIODS)[number];

export const CATEGORIES = [
  'food',
  'groceries',
  'shopping',
  'travel',
  'fuel',
  'bills',
  'rent',
  'education',
  'health',
  'entertainment',
  'subscriptions',
  'cash',
  'transfer',
  'income',
  'fees',
  'investment',
  'other',
] as const;
export type Category = (typeof CATEGORIES)[number];

export interface SpendSummary {
  from: string;
  to: string;
  count: number;
  spent_inr: string;
  received_inr: string;
  net_inr: string;
  by_category: { category: string; total_inr: string; count: number }[];
  top_counterparties: { name: string; total_inr: string; count: number }[];
}

export interface Balance {
  bank: string;
  account: string;
  balance_inr: string;
  as_of: string;
  source: string;
}

export interface Txn {
  id: number;
  date: string;
  direction: 'debit' | 'credit';
  amount_inr: string;
  counterparty: string | null;
  account: string | null;
  category: string | null;
  sources: string[];
}

export interface SmsPayload {
  sender: string;
  body: string;
  received_at: number;
}

export interface DeviceCommand {
  id: string;
  kind: string;
  params: unknown;
  created_at: string;
  expires_at: string;
}

interface RequestOptions {
  body?: unknown;
  timeoutMs?: number;
}

async function send<T>(
  baseUrl: string,
  method: string,
  path: string,
  headers: Record<string, string>,
  { body, timeoutMs = DEFAULT_TIMEOUT_MS }: RequestOptions,
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      method,
      headers: body === undefined ? headers : { ...headers, 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch {
    throw new OfflineError();
  } finally {
    clearTimeout(timer);
  }
  if (!response.ok) throw new ApiError(response.status, await errorDetail(response));
  return (await response.json().catch(() => ({}))) as T;
}

async function errorDetail(response: Response): Promise<string> {
  try {
    const parsed = (await response.json()) as { detail?: unknown };
    if (typeof parsed.detail === 'string') return parsed.detail;
  } catch {
    // Not JSON; fall through to the status text.
  }
  return response.statusText || 'error';
}

async function authContext(): Promise<{ baseUrl: string; headers: Record<string, string> }> {
  const pairing = await loadPairing();
  if (!pairing) throw new ApiError(401, 'not_paired');
  return { baseUrl: pairing.serverUrl, headers: { Authorization: `Bearer ${pairing.token}` } };
}

async function call<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
  const { baseUrl, headers } = await authContext();
  return send<T>(baseUrl, method, path, headers, options);
}

export interface PairResult {
  device_id: string;
  token: string;
  approval_key: string;
  signature_scheme: string;
}

/** The one unauthenticated call. The URL is checked against the Tailscale allowlist first. */
export async function pair(
  serverUrl: string,
  code: string,
  deviceName: string,
): Promise<PairResult> {
  const base = normaliseServerUrl(serverUrl);
  return send<PairResult>(
    base,
    'POST',
    '/pair',
    {},
    {
      body: { code, device_name: deviceName },
    },
  );
}

export const health = () =>
  call<{ status: string }>('GET', '/health', { timeoutMs: HEALTH_TIMEOUT_MS });

export const chat = (message: string, conversationId: string | null) =>
  call<ChatReply>('POST', '/chat', { body: { conversation_id: conversationId, message } });

export interface ChatStreamHandlers {
  onStart?: (conversationId: string) => void;
  onToken: (text: string) => void;
  /** Discard the reply text so far: the model moved on to tool calls or the server failed over. */
  onReset: () => void;
  /** A tool call began or ended. The server sends the tool name and status only. */
  onTool?: (name: string, status: ToolStatus) => void;
}

export interface ChatStreamOptions {
  signal?: AbortSignal;
  inactivityMs?: number;
}

function parseJson(data: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(data);
    return typeof parsed === 'object' && parsed !== null
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

/**
 * Streamed variant of chat(). React Native's fetch cannot read a body incrementally, but its
 * XMLHttpRequest exposes the growing responseText, so the SSE parser is fed from that.
 * The timeout is on inactivity (no bytes), not total time, because replies stream for a while.
 */
export async function chatStream(
  message: string,
  conversationId: string | null,
  handlers: ChatStreamHandlers,
  { signal, inactivityMs = STREAM_INACTIVITY_MS }: ChatStreamOptions = {},
): Promise<ChatReply> {
  const { baseUrl, headers } = await authContext();
  return new Promise<ChatReply>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    let settled = false;
    let seen = 0;
    let checkedHeaders = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    function finish(outcome: () => void) {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener('abort', onAbort);
      outcome();
      xhr.abort();
    }
    const fail = (error: Error) => finish(() => reject(error));
    function onAbort() {
      const error = new Error('aborted');
      error.name = 'AbortError';
      fail(error);
    }
    function armTimer() {
      clearTimeout(timer);
      timer = setTimeout(() => fail(new OfflineError()), inactivityMs);
    }

    const parser = createSseParser(({ event, data }) => {
      const payload = parseJson(data);
      if (!payload || settled) return;
      if (event === 'start' && typeof payload.conversation_id === 'string') {
        handlers.onStart?.(payload.conversation_id);
      } else if (event === 'token' && typeof payload.text === 'string') {
        handlers.onToken(payload.text);
      } else if (event === 'reset') {
        handlers.onReset();
      } else if (event === 'tool') {
        const status = payload.status;
        if (
          typeof payload.name === 'string' &&
          (status === 'started' || status === 'finished' || status === 'failed')
        ) {
          handlers.onTool?.(payload.name, status);
        }
      } else if (event === 'done' && typeof payload.reply === 'string') {
        finish(() => resolve(payload as unknown as ChatReply));
      } else if (event === 'error') {
        const detail = typeof payload.detail === 'string' ? payload.detail : 'error';
        fail(new ApiError(503, detail));
      }
    });

    function drain() {
      if (settled) return;
      armTimer();
      if (xhr.readyState < 3) return;
      if (xhr.status !== 200) return; // Error bodies are JSON: read them once the response ends.
      if (!checkedHeaders) {
        checkedHeaders = true;
        const type = xhr.getResponseHeader('Content-Type') ?? '';
        if (!type.toLowerCase().includes('text/event-stream')) {
          fail(new StreamUnsupportedError());
          return;
        }
      }
      const text = xhr.responseText ?? '';
      if (text.length > seen) {
        const fresh = text.slice(seen);
        seen = text.length;
        parser.push(fresh);
      }
    }

    xhr.onreadystatechange = drain;
    xhr.onprogress = drain;
    xhr.onerror = () => fail(new OfflineError());
    xhr.ontimeout = () => fail(new OfflineError());
    xhr.onabort = () => {
      if (!settled) fail(new OfflineError());
    };
    xhr.onload = () => {
      if (settled) return;
      if (xhr.status !== 200) {
        const body = parseJson(xhr.responseText ?? '');
        const detail = typeof body?.detail === 'string' ? body.detail : xhr.statusText || 'error';
        fail(new ApiError(xhr.status, detail));
        return;
      }
      drain();
      parser.end();
      fail(new StreamUnsupportedError());
    };

    if (signal?.aborted) {
      onAbort();
      return;
    }
    signal?.addEventListener('abort', onAbort);
    xhr.open('POST', `${baseUrl}/chat`);
    xhr.setRequestHeader('Authorization', headers.Authorization);
    xhr.setRequestHeader('Accept', 'text/event-stream');
    xhr.setRequestHeader('Content-Type', 'application/json');
    armTimer();
    xhr.send(JSON.stringify({ conversation_id: conversationId, message }));
  });
}

export const listApprovals = () => call<Approval[]>('GET', '/approvals');

export const getApproval = (id: string) =>
  call<Approval>('GET', `/approvals/${encodeURIComponent(id)}`);

export const listConversations = (
  options: { cursor?: string | null; q?: string; limit?: number } = {},
) => {
  const params = new URLSearchParams();
  if (options.limit !== undefined) params.set('limit', String(options.limit));
  if (options.cursor) params.set('cursor', options.cursor);
  if (options.q?.trim()) params.set('q', options.q.trim());
  const query = params.toString();
  return call<ConversationPage>('GET', `/conversations${query ? `?${query}` : ''}`);
};

export const getConversation = (id: string) =>
  call<ConversationDetail>('GET', `/conversations/${encodeURIComponent(id)}`);

export const renameConversation = (id: string, title: string) =>
  call<ConversationSummary>('PATCH', `/conversations/${encodeURIComponent(id)}`, {
    body: { title },
  });

export const deleteConversation = (id: string) =>
  call<unknown>('DELETE', `/conversations/${encodeURIComponent(id)}`);

/** The server's answer to a decision. `result` is only present once the action has executed. */
export interface DecisionResult {
  id: string;
  status: string;
  result?: unknown;
}

export const decideApproval = (
  id: string,
  decision: 'approve' | 'reject',
  proof: { payload_hash: string; nonce: string; sig: string },
) => call<DecisionResult>('POST', `/approvals/${id}/${decision}`, { body: proof });

export interface MailAddress {
  name: string;
  addr: string;
}

export interface MailAttachment {
  name: string;
  size: number;
  mime: string;
}

/** One mail as the agent returns it: plain-text body, attachment metadata only. */
export interface MailMessage {
  account: string;
  id: string;
  thread_id: string;
  from: MailAddress;
  to: MailAddress[];
  cc: MailAddress[];
  date: string;
  subject: string;
  labels: string[];
  category: string | null;
  reason: string | null;
  body: string;
  body_truncated: boolean;
  attachments: MailAttachment[];
  /** "stored": Gmail was unreachable, so cc and attachments may be incomplete. */
  source: 'live' | 'stored';
}

export const getMailMessage = (account: string, id: string) =>
  call<MailMessage>('GET', `/mail/${encodeURIComponent(account)}/${encodeURIComponent(id)}`);

export const getToday = () => call<Today>('GET', '/today');

export const getSummary = (period: Period) =>
  call<SpendSummary>('GET', `/finance/summary?period=${period}`);

export const getBalances = () => call<{ accounts: Balance[] }>('GET', '/finance/balances');

export const getTransactions = (period: Period, limit = 50) =>
  call<{ total: number; transactions: Txn[] }>(
    'GET',
    `/finance/transactions?period=${period}&limit=${limit}`,
  );

export const setCategory = (txnId: number, category: Category) =>
  call<{ status: string }>('POST', '/finance/category', {
    body: { txn_id: txnId, category, remember: true },
  });

export const postSms = (messages: SmsPayload[]) =>
  call<Record<string, number>>('POST', '/sms', { body: { messages } });

export const getSmsSenders = () => call<{ senders: string[] }>('GET', '/sms/senders');

export const getDeviceCommands = () =>
  call<{ commands: DeviceCommand[] }>('GET', '/device/commands');

export const ackDeviceCommand = (id: string, result: 'done' | 'failed') =>
  call<{ id: string; status: string }>('POST', `/device/commands/${id}/ack`, { body: { result } });

export const putPushToken = (token: string) =>
  call<unknown>('PUT', '/device/push-token', { body: { token } });

export const deletePushToken = () => call<unknown>('DELETE', '/device/push-token');
