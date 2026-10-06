import {
  BASE_CPS,
  MAX_LAG_CHARS,
  nextRevealLength,
  splitSettled,
  tailWords,
} from '../streamText';

describe('splitSettled', () => {
  it('keeps everything open until a block is closed by a blank line', () => {
    expect(splitSettled('Hello there')).toEqual({ settled: '', tail: 'Hello there' });
    expect(splitSettled('First para.\n')).toEqual({ settled: '', tail: 'First para.\n' });
  });

  it('settles whole blocks once the next one has started', () => {
    const text = 'First para.\n\nSecond';
    expect(splitSettled(text)).toEqual({ settled: 'First para.\n\n', tail: 'Second' });
    // The blank line alone (nothing after it yet) is not final.
    expect(splitSettled('First para.\n\n').settled).toBe('First para.\n\n');
  });

  it('never splits inside a code fence', () => {
    const open = 'Intro.\n\n```py\nx = 1\n\ny = 2';
    expect(splitSettled(open)).toEqual({ settled: 'Intro.\n\n', tail: '```py\nx = 1\n\ny = 2' });
    const closed = `${open}\n\`\`\`\n\nAfter`;
    expect(splitSettled(closed).tail).toBe('After');
  });

  it('settled plus tail is always the whole text', () => {
    const text = '# Title\n\n- a\n- b\n\n| x |\n| - |\n\nend';
    for (let i = 0; i <= text.length; i += 1) {
      const { settled, tail } = splitSettled(text.slice(0, i));
      expect(settled + tail).toBe(text.slice(0, i));
    }
  });
});

describe('nextRevealLength', () => {
  const text = 'The quick brown fox jumps over the lazy dog';

  it('reveals whole words, at least one per step', () => {
    const next = nextRevealLength(0, text, 1);
    expect(next).toBe(3); // "The"
    expect(nextRevealLength(next, text, 1)).toBe(9); // " quick"
  });

  it('never goes past what has arrived', () => {
    expect(nextRevealLength(0, text, 10_000)).toBe(text.length);
    expect(nextRevealLength(text.length, text, 16)).toBe(text.length);
  });

  it('speeds up as the backlog grows', () => {
    const small = 'word '.repeat(10);
    const large = 'word '.repeat(100);
    const step = (t: string) => nextRevealLength(0, t, 16);
    expect(step(large)).toBeGreaterThan(step(small));
    // A small backlog moves at about the base pace.
    expect(nextRevealLength(0, 'a'.repeat(5) + ' '.repeat(200), 1000)).toBeGreaterThanOrEqual(
      BASE_CPS,
    );
  });

  it('never lags more than the cap behind', () => {
    const huge = 'x '.repeat(MAX_LAG_CHARS * 2);
    expect(huge.length - nextRevealLength(0, huge, 16)).toBeLessThanOrEqual(MAX_LAG_CHARS);
  });

  it('catches up with a steady stream within a few seconds of frames', () => {
    let shown = 0;
    let text2 = '';
    for (let frame = 0; frame < 600; frame += 1) {
      if (frame % 3 === 0) text2 += 'token ';
      shown = nextRevealLength(shown, text2, 16);
    }
    expect(text2.length - shown).toBeLessThan(40);
  });
});

describe('tailWords', () => {
  it('splits into words with trailing spaces and separate newlines, keyed by offset', () => {
    expect(tailWords('Hi there\nnext', 10)).toEqual([
      { key: 10, text: 'Hi ' },
      { key: 13, text: 'there' },
      { key: 18, text: '\n' },
      { key: 19, text: 'next' },
    ]);
  });

  it('keeps keys stable as more text arrives', () => {
    const before = tailWords('one two', 0);
    const after = tailWords('one two three', 0);
    expect(after.slice(0, 1)).toEqual(before.slice(0, 1));
    expect(after.map((w) => w.key)).toEqual([0, 4, 8]);
  });
});
