import { normaliseServerUrl, parsePairingQr } from '../serverUrl';

describe('normaliseServerUrl', () => {
  it.each([
    ['http://100.64.0.1:8765', 'http://100.64.0.1:8765'],
    ['http://100.64.0.1', 'http://100.64.0.1'],
    ['http://100.127.255.255:8765/', 'http://100.127.255.255:8765'],
    ['http://[fd7a:115c:a1e0::1]:8765', 'http://[fd7a:115c:a1e0::1]:8765'],
    ['  http://100.100.100.100:8765 ', 'http://100.100.100.100:8765'],
  ])('accepts %s', (input, expected) => {
    expect(normaliseServerUrl(input)).toBe(expected);
  });

  it.each([
    'http://100.63.255.255:8765',
    'http://100.128.0.1:8765',
    'http://192.168.1.5:8765',
    'http://127.0.0.1:8765',
    'http://0.0.0.0:8765',
    'https://ts.net',
    'https://evil.tailnet-name.ts.net',
    'http://laptop.tailnet.ts.net:8765',
    'https://laptop.tail1234.ts.net',
    'https://100.64.0.1:8765',
    'https://[fd7a:115c:a1e0::1]:8765',
    'http://localhost:8765',
    'https://evil.com',
    'https://evil.com.ts.net.evil.com',
    'http://100.64.0.1/x',
    'http://100.64.0.1:8765?x=1',
    'http://user:pw@[fd7a:115c:a1e0::1]:8765',
    'ftp://100.64.0.1',
    'http://[fd7a:115c:a1e1::1]:8765',
    'http://100.064.0.1',
    'http://100.64.0.1:99999',
  ])('rejects %s', (input) => {
    expect(() => normaliseServerUrl(input)).toThrow();
  });
});

describe('parsePairingQr', () => {
  const qr = (obj: unknown) => JSON.stringify(obj);

  it('parses a valid code', () => {
    expect(
      parsePairingQr(qr({ v: 1, url: 'http://100.64.0.1:8765/', code: 'abc_DEF-123' })),
    ).toEqual({
      url: 'http://100.64.0.1:8765',
      code: 'abc_DEF-123',
    });
  });

  it.each([
    ['bad JSON', '{nope'],
    ['not an object', '"x"'],
    ['wrong version', qr({ v: 2, url: 'http://100.64.0.1:8765', code: 'abc' })],
    ['bad code characters', qr({ v: 1, url: 'http://100.64.0.1:8765', code: 'ab c!' })],
    ['empty code', qr({ v: 1, url: 'http://100.64.0.1:8765', code: '' })],
    ['non-Tailscale url', qr({ v: 1, url: 'http://192.168.1.5:8765', code: 'abc' })],
    ['missing url', qr({ v: 1, code: 'abc' })],
  ])('rejects %s', (_name, data) => {
    expect(() => parsePairingQr(data)).toThrow();
  });
});
