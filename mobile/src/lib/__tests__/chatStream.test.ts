import { ApiError, chatStream, OfflineError, StreamUnsupportedError } from '../api';
import { loadPairing } from '../secureKeys';

jest.mock('../secureKeys', () => ({ loadPairing: jest.fn() }));

class FakeXhr {
  static last: FakeXhr;
  readyState = 0;
  status = 0;
  statusText = '';
  responseText = '';
  headers: Record<string, string> = {};
  sent: string | null = null;
  requestHeaders: Record<string, string> = {};
  url = '';
  aborted = false;
  onreadystatechange: (() => void) | null = null;
  onprogress: (() => void) | null = null;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  ontimeout: (() => void) | null = null;
  onabort: (() => void) | null = null;

  constructor() {
    FakeXhr.last = this;
  }
  open(_method: string, url: string) {
    this.url = url;
  }
  setRequestHeader(name: string, value: string) {
    this.requestHeaders[name] = value;
  }
  getResponseHeader(name: string) {
    return this.headers[name.toLowerCase()] ?? null;
  }
  send(body: string) {
    this.sent = body;
  }
  abort() {
    this.aborted = true;
    this.onabort?.();
  }

  respond(status: number, contentType: string) {
    this.status = status;
    this.headers['content-type'] = contentType;
    this.readyState = 2;
    this.onreadystatechange?.();
  }
  chunk(text: string) {
    this.responseText += text;
    this.readyState = 3;
    this.onreadystatechange?.();
    this.onprogress?.();
  }
  finish() {
    this.readyState = 4;
    this.onreadystatechange?.();
    this.onload?.();
  }
}

const ev = (name: string, data: unknown) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
const DONE = { conversation_id: 'c1', reply: 'Hello there', pending_action_ids: ['a1'] };

function setup() {
  const calls: string[] = [];
  const promise = chatStream('hi', null, {
    onStart: (id) => calls.push(`start:${id}`),
    onToken: (t) => calls.push(`token:${t}`),
    onReset: () => calls.push('reset'),
    onTool: (name, status) => calls.push(`tool:${name}:${status}`),
  });
  return { calls, promise };
}

async function started() {
  // chatStream awaits the pairing lookup before creating the request.
  await Promise.resolve();
  await Promise.resolve();
  return FakeXhr.last;
}

beforeEach(() => {
  (globalThis as unknown as { XMLHttpRequest: unknown }).XMLHttpRequest = FakeXhr;
  jest.mocked(loadPairing).mockResolvedValue({
    serverUrl: 'http://100.64.0.1:8765',
    token: 'tok',
  } as never);
});

afterEach(() => jest.useRealTimers());

describe('chatStream', () => {
  it('sends an authenticated streaming request', async () => {
    const { promise } = setup();
    const xhr = await started();
    expect(xhr.url).toBe('http://100.64.0.1:8765/chat');
    expect(xhr.requestHeaders.Authorization).toBe('Bearer tok');
    expect(xhr.requestHeaders.Accept).toBe('text/event-stream');
    expect(JSON.parse(xhr.sent ?? '')).toEqual({ conversation_id: null, message: 'hi' });
    xhr.respond(200, 'text/event-stream');
    xhr.chunk(ev('done', DONE));
    await promise;
  });

  it('streams tokens then resolves with the done payload', async () => {
    const { calls, promise } = setup();
    const xhr = await started();
    xhr.respond(200, 'text/event-stream; charset=utf-8');
    xhr.chunk(ev('start', { conversation_id: 'c1' }) + ev('token', { text: 'Hello' }));
    xhr.chunk(ev('token', { text: ' there' }).slice(0, 12));
    xhr.chunk(ev('token', { text: ' there' }).slice(12) + ev('done', DONE));
    await expect(promise).resolves.toEqual(DONE);
    expect(calls).toEqual(['start:c1', 'token:Hello', 'token: there']);
  });

  it('forwards reset events', async () => {
    const { calls, promise } = setup();
    const xhr = await started();
    xhr.respond(200, 'text/event-stream');
    xhr.chunk(ev('token', { text: 'draft' }) + ev('reset', {}) + ev('token', { text: 'real' }));
    xhr.chunk(ev('done', DONE));
    await promise;
    expect(calls).toEqual(['token:draft', 'reset', 'token:real']);
  });

  it('rejects with a 503 ApiError on an error event', async () => {
    const { promise } = setup();
    const xhr = await started();
    xhr.respond(200, 'text/event-stream');
    xhr.chunk(ev('error', { detail: 'model_unavailable' }));
    await expect(promise).rejects.toMatchObject({ status: 503, detail: 'model_unavailable' });
    await expect(promise).rejects.toBeInstanceOf(ApiError);
  });

  it('rejects with the JSON detail on a non-200 response', async () => {
    const { promise } = setup();
    const xhr = await started();
    xhr.respond(401, 'application/json');
    xhr.chunk('{"detail":"bad_token"}');
    xhr.finish();
    await expect(promise).rejects.toMatchObject({ status: 401, detail: 'bad_token' });
  });

  it('rejects with StreamUnsupportedError for a non-SSE 200', async () => {
    const { promise } = setup();
    const xhr = await started();
    xhr.respond(200, 'application/json');
    xhr.chunk('{"reply":"x"}');
    xhr.finish();
    await expect(promise).rejects.toBeInstanceOf(StreamUnsupportedError);
  });

  it('rejects with StreamUnsupportedError when the stream ends without done', async () => {
    const { promise } = setup();
    const xhr = await started();
    xhr.respond(200, 'text/event-stream');
    xhr.chunk(ev('token', { text: 'partial' }));
    xhr.finish();
    await expect(promise).rejects.toBeInstanceOf(StreamUnsupportedError);
  });

  it('rejects with OfflineError on a network error', async () => {
    const { promise } = setup();
    const xhr = await started();
    xhr.onerror?.();
    await expect(promise).rejects.toBeInstanceOf(OfflineError);
  });

  it('rejects with OfflineError after the inactivity timeout, which resets on bytes', async () => {
    jest.useFakeTimers();
    const { promise } = setup();
    const caught = promise.catch((e: unknown) => e);
    await jest.advanceTimersByTimeAsync(0);
    const xhr = FakeXhr.last;
    xhr.respond(200, 'text/event-stream');
    await jest.advanceTimersByTimeAsync(50_000);
    xhr.chunk(ev('token', { text: 'a' }));
    await jest.advanceTimersByTimeAsync(50_000);
    xhr.chunk(ev('token', { text: 'b' }));
    await jest.advanceTimersByTimeAsync(60_000);
    expect(await caught).toBeInstanceOf(OfflineError);
    expect(xhr.aborted).toBe(true);
  });

  it('rejects when the signal aborts', async () => {
    const controller = new AbortController();
    const promise = chatStream(
      'hi',
      null,
      { onToken: jest.fn(), onReset: jest.fn() },
      {
        signal: controller.signal,
      },
    );
    const caught = promise.catch((e: unknown) => e);
    await started();
    controller.abort();
    expect(await caught).toMatchObject({ name: 'AbortError' });
  });

  it('forwards tool events in order with the tokens around them', async () => {
    const { calls, promise } = setup();
    const xhr = await started();
    xhr.respond(200, 'text/event-stream');
    xhr.chunk(
      ev('start', { conversation_id: 'c1' }) +
        ev('token', { text: 'Checking.' }) +
        ev('reset', {}) +
        ev('tool', { name: 'mail_search', status: 'started' }),
    );
    xhr.chunk(
      ev('tool', { name: 'mail_search', status: 'finished' }) +
        ev('tool', { name: 'balances', status: 'started' }) +
        ev('tool', { name: 'balances', status: 'failed' }) +
        ev('token', { text: 'Done' }) +
        ev('done', DONE),
    );
    await promise;
    expect(calls).toEqual([
      'start:c1',
      'token:Checking.',
      'reset',
      'tool:mail_search:started',
      'tool:mail_search:finished',
      'tool:balances:started',
      'tool:balances:failed',
      'token:Done',
    ]);
  });

  it('parses a tool event split across chunks', async () => {
    const { calls, promise } = setup();
    const xhr = await started();
    xhr.respond(200, 'text/event-stream');
    const raw = ev('tool', { name: 'drive_search', status: 'started' });
    xhr.chunk(raw.slice(0, 15));
    xhr.chunk(raw.slice(15) + ev('done', DONE));
    await promise;
    expect(calls).toEqual(['tool:drive_search:started']);
  });

  it('ignores malformed tool events and unknown statuses', async () => {
    const { calls, promise } = setup();
    const xhr = await started();
    xhr.respond(200, 'text/event-stream');
    xhr.chunk(
      ev('tool', { name: 'mail_search', status: 'exploded' }) +
        ev('tool', { status: 'started' }) +
        ev('tool', { name: 7, status: 'started' }) +
        'event: tool\ndata: not json\n\n' +
        ev('done', DONE),
    );
    await promise;
    expect(calls).toEqual([]);
  });

  it('still works for a server that sends no tool events', async () => {
    const { calls, promise } = setup();
    const xhr = await started();
    xhr.respond(200, 'text/event-stream');
    xhr.chunk(ev('token', { text: 'Hi' }) + ev('done', DONE));
    await expect(promise).resolves.toEqual(DONE);
    expect(calls).toEqual(['token:Hi']);
  });
});

describe('chatStream sources', () => {
  it('passes validated sources from the done event, capped at five', async () => {
    const { promise } = setup();
    const xhr = await started();
    xhr.respond(200, 'text/event-stream');
    const sources = [
      { title: 'Bad', url: 'javascript:alert(1)' },
      ...Array.from({ length: 7 }, (_, i) => ({
        title: `Page ${i}`,
        url: `https://example.com/${i}`,
      })),
    ];
    xhr.chunk(ev('done', { ...DONE, sources }));
    const reply = await promise;
    expect(reply.sources).toHaveLength(5);
    expect(reply.sources?.[0]).toEqual({ title: 'Page 0', url: 'https://example.com/0' });
  });

  it('leaves the reply as it was when sources are missing, empty or not a list', async () => {
    for (const sources of [undefined, [], 'https://example.com', [{ url: 'intent://x' }]]) {
      const { promise } = setup();
      const xhr = await started();
      xhr.respond(200, 'text/event-stream');
      xhr.chunk(ev('done', { ...DONE, sources }));
      await expect(promise).resolves.toEqual(DONE);
    }
  });
});
