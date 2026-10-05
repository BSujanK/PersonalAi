import {
  deleteConversation,
  getApproval,
  getConversation,
  listConversations,
  renameConversation,
  ApiError,
  OfflineError,
} from '../api';
import { loadPairing } from '../secureKeys';

jest.mock('../secureKeys', () => ({ loadPairing: jest.fn() }));

const BASE = 'http://100.64.0.1:8765';
const fetchMock = jest.fn();

function reply(status: number, body?: unknown) {
  fetchMock.mockResolvedValueOnce({
    ok: status >= 200 && status < 300,
    status,
    statusText: 'x',
    json: async () => {
      if (body === undefined) throw new Error('no body');
      return body;
    },
  });
}

function lastCall() {
  const [url, init] = fetchMock.mock.calls[fetchMock.mock.calls.length - 1] as [
    string,
    RequestInit,
  ];
  return { url, init, headers: init.headers as Record<string, string> };
}

beforeEach(() => {
  fetchMock.mockReset();
  (globalThis as unknown as { fetch: unknown }).fetch = fetchMock;
  jest.mocked(loadPairing).mockResolvedValue({ serverUrl: BASE, token: 'tok' } as never);
});

describe('conversation API client', () => {
  it('lists conversations with the device token and no query by default', async () => {
    const page = { items: [], next_cursor: null };
    reply(200, page);
    await expect(listConversations()).resolves.toEqual(page);
    const { url, init, headers } = lastCall();
    expect(url).toBe(`${BASE}/conversations`);
    expect(init.method).toBe('GET');
    expect(headers.Authorization).toBe('Bearer tok');
  });

  it('passes limit, cursor and search text as query parameters', async () => {
    reply(200, { items: [], next_cursor: null });
    await listConversations({
      limit: 30,
      cursor: '2026-10-05T12:00:00+00:00|abc',
      q: ' due soon ',
    });
    const url = new URL(lastCall().url);
    expect(url.pathname).toBe('/conversations');
    expect(url.searchParams.get('limit')).toBe('30');
    expect(url.searchParams.get('cursor')).toBe('2026-10-05T12:00:00+00:00|abc');
    expect(url.searchParams.get('q')).toBe('due soon');
  });

  it('skips a blank search', async () => {
    reply(200, { items: [], next_cursor: null });
    await listConversations({ q: '   ' });
    expect(lastCall().url).toBe(`${BASE}/conversations`);
  });

  it('opens one conversation, encoding the id', async () => {
    const detail = { id: 'a/b', title: 'T', updated_at: 'x', messages: [] };
    reply(200, detail);
    await expect(getConversation('a/b')).resolves.toEqual(detail);
    expect(lastCall().url).toBe(`${BASE}/conversations/a%2Fb`);
  });

  it('renames with a PATCH body', async () => {
    reply(200, { id: 'c1', title: 'Trip', updated_at: 'x', preview: '' });
    const out = await renameConversation('c1', 'Trip');
    expect(out.title).toBe('Trip');
    const { url, init, headers } = lastCall();
    expect(url).toBe(`${BASE}/conversations/c1`);
    expect(init.method).toBe('PATCH');
    expect(JSON.parse(init.body as string)).toEqual({ title: 'Trip' });
    expect(headers['Content-Type']).toBe('application/json');
  });

  it('deletes and tolerates the empty 204 body', async () => {
    reply(204);
    await expect(deleteConversation('c1')).resolves.toEqual({});
    const { url, init } = lastCall();
    expect(url).toBe(`${BASE}/conversations/c1`);
    expect(init.method).toBe('DELETE');
  });

  it('fetches a single approval', async () => {
    reply(200, { id: 'a1' });
    await getApproval('a1');
    expect(lastCall().url).toBe(`${BASE}/approvals/a1`);
  });

  it('turns HTTP failures into ApiError and network failures into OfflineError', async () => {
    reply(404, { detail: 'conversation not found' });
    await expect(getConversation('nope')).rejects.toMatchObject({
      status: 404,
      detail: 'conversation not found',
    });
    reply(401, { detail: 'unauthorized' });
    await expect(listConversations()).rejects.toBeInstanceOf(ApiError);
    fetchMock.mockRejectedValueOnce(new TypeError('Network request failed'));
    await expect(listConversations()).rejects.toBeInstanceOf(OfflineError);
  });

  it('refuses to call when the phone is not paired', async () => {
    jest.mocked(loadPairing).mockResolvedValue(null);
    await expect(listConversations()).rejects.toMatchObject({ status: 401, detail: 'not_paired' });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
