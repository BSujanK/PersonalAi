import { MAX_SOURCES, parseSources, sourceHost, truncateTitle } from '../sources';

describe('sourceHost', () => {
  it('names the site without www, port or case', () => {
    expect(sourceHost('https://www.Example.com/a/b?x=1')).toBe('example.com');
    expect(sourceHost('http://docs.example.org:8080/')).toBe('docs.example.org');
  });

  it('refuses anything that is not a plain http(s) address', () => {
    for (const url of [
      'javascript:alert(1)',
      'intent://x#Intent;end',
      'mailto:me@example.com',
      'file:///etc/passwd',
      'ftp://example.com/x',
      'https://user:pw@example.com/',
      'https://exa mple.com/',
      'https://localhost-only/',
      'example.com/path',
      '',
    ]) {
      expect(sourceHost(url)).toBeNull();
    }
  });
});

describe('parseSources', () => {
  it('keeps well-formed entries with their titles', () => {
    expect(
      parseSources([
        { title: 'Release notes', url: 'https://example.com/notes' },
        { title: '  Spaced   out  title ', url: 'http://news.example.org/a' },
      ]),
    ).toEqual([
      { title: 'Release notes', url: 'https://example.com/notes' },
      { title: 'Spaced out title', url: 'http://news.example.org/a' },
    ]);
  });

  it('drops entries with a bad URL or the wrong shape, and tolerates a missing field', () => {
    expect(parseSources(undefined)).toEqual([]);
    expect(parseSources('https://example.com')).toEqual([]);
    expect(parseSources({ url: 'https://example.com' })).toEqual([]);
    expect(
      parseSources([
        null,
        'https://example.com',
        { title: 'No url' },
        { title: 'Bad scheme', url: 'javascript:alert(1)' },
        { title: 'Intent', url: 'intent://x' },
        { title: 'Number', url: 42 },
        { title: 'Good', url: 'https://example.com/ok' },
        { title: 7, url: 'https://example.org/no-title' },
      ]),
    ).toEqual([
      { title: 'Good', url: 'https://example.com/ok' },
      { title: 'example.org', url: 'https://example.org/no-title' },
    ]);
  });

  it('keeps at most five, in order, without duplicates', () => {
    const many = Array.from({ length: 9 }, (_, i) => ({
      title: `Page ${i}`,
      url: `https://example.com/${i}`,
    }));
    const parsed = parseSources([many[0], many[0], ...many]);
    expect(parsed).toHaveLength(MAX_SOURCES);
    expect(parsed.map((s) => s.title)).toEqual(['Page 0', 'Page 1', 'Page 2', 'Page 3', 'Page 4']);
  });

  it('caps a very long title and refuses a very long URL', () => {
    const [source] = parseSources([{ title: 'x'.repeat(500), url: 'https://example.com/' }]);
    expect(source.title).toHaveLength(200);
    const long = `https://example.com/${'a'.repeat(3000)}`;
    expect(parseSources([{ title: 't', url: long }])).toEqual([]);
  });
});

describe('truncateTitle', () => {
  it('shortens with an ellipsis only when needed', () => {
    expect(truncateTitle('Short title')).toBe('Short title');
    const cut = truncateTitle('A rather long article title that keeps going', 20);
    expect(cut).toHaveLength(20);
    expect(cut.endsWith('…')).toBe(true);
  });
});
