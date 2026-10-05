import { createSseParser, type SseEvent } from '../sse';

const STREAM =
  'event: start\ndata: {"conversation_id":"c1"}\n\n' +
  ': keep-alive\n\n' +
  'event: token\ndata: {"text":"Hel"}\n\n' +
  'data: line one\ndata: line two\n\n' +
  'event: done\ndata: {"reply":"Hello"}\n\n';

const EXPECTED: SseEvent[] = [
  { event: 'start', data: '{"conversation_id":"c1"}' },
  { event: 'token', data: '{"text":"Hel"}' },
  { event: 'message', data: 'line one\nline two' },
  { event: 'done', data: '{"reply":"Hello"}' },
];

function parse(chunks: string[]): SseEvent[] {
  const events: SseEvent[] = [];
  const parser = createSseParser((e) => events.push(e));
  chunks.forEach((c) => parser.push(c));
  parser.end();
  return events;
}

describe('createSseParser', () => {
  it('parses a whole stream in one chunk', () => {
    expect(parse([STREAM])).toEqual(EXPECTED);
  });

  it('parses the same events when split at every character position', () => {
    for (let i = 0; i <= STREAM.length; i++) {
      expect(parse([STREAM.slice(0, i), STREAM.slice(i)])).toEqual(EXPECTED);
    }
  });

  it('parses one character at a time', () => {
    expect(parse([...STREAM])).toEqual(EXPECTED);
  });

  it('handles CRLF line endings split at every position', () => {
    const crlf = STREAM.replace(/\n/g, '\r\n');
    for (let i = 0; i <= crlf.length; i++) {
      expect(parse([crlf.slice(0, i), crlf.slice(i)])).toEqual(EXPECTED);
    }
  });

  it('ignores comments and fields without a value', () => {
    expect(parse([': hi\ndata\n\n'])).toEqual([{ event: 'message', data: '' }]);
  });

  it('drops an event left incomplete at the end of the stream', () => {
    expect(parse(['event: token\ndata: {"text":"x"}\n'])).toEqual([]);
  });
});
