// Typed client for the laptop agent. Every route except /pair sends the device bearer token.
import { loadPairing } from './secureKeys';
import { normaliseServerUrl } from './serverUrl';

const DEFAULT_TIMEOUT_MS = 15_000;
const HEALTH_TIMEOUT_MS = 5_000;

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

async function call<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
  const pairing = await loadPairing();
  if (!pairing) throw new ApiError(401, 'not_paired');
  return send<T>(
    pairing.serverUrl,
    method,
    path,
    { Authorization: `Bearer ${pairing.token}` },
    options,
  );
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

export const listApprovals = () => call<Approval[]>('GET', '/approvals');

export const decideApproval = (
  id: string,
  decision: 'approve' | 'reject',
  proof: { payload_hash: string; nonce: string; sig: string },
) => call<{ id: string; status: string }>('POST', `/approvals/${id}/${decision}`, { body: proof });

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
