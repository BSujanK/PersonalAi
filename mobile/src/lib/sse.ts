// Incremental Server-Sent Events parser. Pure: feed it text chunks split anywhere and it emits
// complete events. An event still open when the stream ends is discarded, as the SSE spec says.

export interface SseEvent {
  event: string;
  data: string;
}

export interface SseParser {
  push(chunk: string): void;
  end(): void;
}

export function createSseParser(onEvent: (event: SseEvent) => void): SseParser {
  let buffer = '';
  let eventName = '';
  let dataLines: string[] = [];

  function handleLine(line: string) {
    if (line === '') {
      if (dataLines.length > 0)
        onEvent({ event: eventName || 'message', data: dataLines.join('\n') });
      eventName = '';
      dataLines = [];
      return;
    }
    if (line.startsWith(':')) return;
    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    if (field === 'event') eventName = value;
    else if (field === 'data') dataLines.push(value);
  }

  return {
    push(chunk) {
      buffer += chunk;
      let start = 0;
      for (let i = 0; i < buffer.length; i++) {
        const ch = buffer[i];
        if (ch !== '\n' && ch !== '\r') continue;
        // A trailing CR may be the first half of CRLF: wait for the next chunk to know.
        if (ch === '\r' && i === buffer.length - 1) break;
        handleLine(buffer.slice(start, i));
        if (ch === '\r' && buffer[i + 1] === '\n') i++;
        start = i + 1;
      }
      buffer = buffer.slice(start);
    },
    end() {
      buffer = '';
      eventName = '';
      dataLines = [];
    },
  };
}
