import { fireEvent, render, screen } from '@testing-library/react-native';
import * as Clipboard from 'expo-clipboard';
import { Alert, Linking } from 'react-native';

import { lightPalette } from '../../../theme';

import { isSafeLink, parseMarkdown, plainText } from '../../../lib/markdown';
import { Markdown } from '../Markdown';

jest.mock('expo-clipboard', () => ({ setStringAsync: jest.fn().mockResolvedValue(true) }));

const DOC = [
  '# Weekly summary',
  '',
  'You have **two** deadlines and *one* exam. See [the portal](https://portal.example.com/x).',
  '',
  '- Essay due Friday',
  '- Lab report due Monday',
  '',
  '1. First',
  '2. Second',
  '',
  '| Item | Amount |',
  '| --- | ---: |',
  '| Books | 1200 |',
  '| Fees | 5000 |',
  '',
  '```python',
  'print("hello")',
  '```',
].join('\n');

jest.setTimeout(30_000);

describe('Markdown', () => {
  beforeEach(() => jest.clearAllMocks());

  it('renders headings, emphasis, lists, tables and code', async () => {
    await render(<Markdown text={DOC} />);
    expect(screen.getByText('Weekly summary')).toBeTruthy();
    expect(screen.getByText('Essay due Friday')).toBeTruthy();
    expect(screen.getByText('Lab report due Monday')).toBeTruthy();
    expect(screen.getByText('First')).toBeTruthy();
    expect(screen.getByText('2.')).toBeTruthy();
    expect(screen.getByText('Item')).toBeTruthy();
    expect(screen.getByText('5000')).toBeTruthy();
    expect(screen.getByText('print("hello")')).toBeTruthy();
    expect(screen.getByText('python')).toBeTruthy();
    expect(screen.getByRole('header', { name: 'Weekly summary' })).toBeTruthy();
  });

  it('copies a fenced code block', async () => {
    await render(<Markdown text={DOC} />);
    await fireEvent.press(screen.getByLabelText('Copy code'));
    expect(Clipboard.setStringAsync).toHaveBeenCalledWith('print("hello")\n');
    expect(await screen.findByLabelText('Copied')).toBeTruthy();
  });

  it('asks before opening a link, and only for http(s) and mailto', async () => {
    const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
    const open = jest.spyOn(Linking, 'openURL').mockResolvedValue(true);
    await render(<Markdown text={'[safe](https://portal.example.com/x) and [bad](intent://x)'} />);
    await fireEvent.press(screen.getByRole('link', { name: 'safe' }));
    expect(alert).toHaveBeenCalledTimes(1);
    expect(alert.mock.calls[0][1]).toBe('https://portal.example.com/x');
    expect(open).not.toHaveBeenCalled(); // nothing opens until the owner confirms
    expect(screen.queryByRole('link', { name: 'bad' })).toBeNull();
    expect(screen.getByText('bad')).toBeTruthy();
  });

  it('never loads images and shows raw HTML as text', async () => {
    await render(<Markdown text={'![tracker](https://evil.example.com/p.png) <b>hi</b>'} />);
    expect(screen.getByText(/\[image: tracker\]/)).toBeTruthy();
    expect(screen.getByText(/<b>hi<\/b>/)).toBeTruthy();
  });

  it('hangs list text beside real bullets and numbers, with nested levels', async () => {
    const nested = [
      '- Fruit',
      '  - Apples',
      '    - Gala',
      '- Veg',
      '',
      '3. Third',
      '4. Fourth',
    ].join('\n');
    await render(<Markdown text={nested} />);
    // Solid, hollow and square bullets by depth.
    expect(screen.getAllByText('•')).toHaveLength(2);
    expect(screen.getAllByText('◦')).toHaveLength(1);
    expect(screen.getAllByText('▪')).toHaveLength(1);
    expect(screen.getByText('Gala')).toBeTruthy();
    // An ordered list keeps its start number.
    expect(screen.getByText('3.')).toBeTruthy();
    expect(screen.getByText('4.')).toBeTruthy();
  });

  it('puts a table in a horizontal scroller with a header row and padded cells', async () => {
    await render(<Markdown text={DOC} />);
    const scroller = screen.getByTestId('md-table');
    expect(scroller.props.horizontal).toBe(true);
    expect(screen.getByText('Item')).toHaveStyle({ fontFamily: 'HankenGrotesk_600SemiBold' });
    expect(screen.getByText('Books')).not.toHaveStyle({ fontFamily: 'HankenGrotesk_600SemiBold' });
    expect(screen.getByText('1200')).toHaveStyle({ textAlign: 'right' });
  });

  it('labels a fenced block with its language and falls back to "code"', async () => {
    await render(<Markdown text={'```ts\nconst a = 1;\n```\n\n```\nplain\n```'} />);
    expect(screen.getByText('ts')).toBeTruthy();
    expect(screen.getByText('code')).toBeTruthy();
    expect(screen.getAllByLabelText('Copy code')).toHaveLength(2);
  });

  it('sets a block quote off with a violet rule', async () => {
    await render(<Markdown text={'> Quoted words\n> second line'} />);
    expect(screen.getByTestId('md-quote')).toHaveStyle({
      borderLeftWidth: 3,
      borderLeftColor: lightPalette.accent,
    });
    expect(screen.getByText(/Quoted words/)).toBeTruthy();
  });

  it('sets headings in the display serif at modest sizes, and figures in tabular numerals', async () => {
    await render(
      <Markdown text={'# One\n\n## Two\n\n### Three\n\nTotal ₹12,450 due 14 Oct 2026'} />,
    );
    for (const [name, size] of [
      ['One', 23],
      ['Two', 20],
      ['Three', 18],
    ] as const) {
      expect(screen.getByRole('header', { name })).toHaveStyle({
        fontFamily: 'Newsreader_500Medium',
        fontSize: size,
      });
    }
    expect(screen.getByText(/₹12,450/)).toHaveStyle({ fontVariant: ['tabular-nums'] });
  });

  it('draws a rule between sections', async () => {
    await render(<Markdown text={'Above\n\n---\n\nBelow'} />);
    expect(screen.getByText('Above')).toBeTruthy();
    expect(screen.getByText('Below')).toBeTruthy();
    expect(screen.getByTestId('md-rule')).toHaveStyle({
      height: 1,
      backgroundColor: lightPalette.separator,
    });
  });

  it('handles an unfinished code fence while streaming', async () => {
    await render(<Markdown text={'Running:\n```\nstep one'} />);
    expect(screen.getByText('step one')).toBeTruthy();
    expect(screen.getByLabelText('Copy code')).toBeTruthy();
  });
});

describe('markdown helpers', () => {
  it('classifies links', () => {
    expect(isSafeLink('https://a.example.com')).toBe(true);
    expect(isSafeLink('mailto:me@example.com')).toBe(true);
    expect(isSafeLink('javascript:alert(1)')).toBe(false);
    expect(isSafeLink('intent://x')).toBe(false);
    expect(isSafeLink(null)).toBe(false);
  });

  it('builds a tree with inline children', () => {
    const [paragraph] = parseMarkdown('Hello **world**');
    expect(paragraph.type).toBe('paragraph');
    expect(plainText(paragraph.children)).toBe('Hello world');
  });
});
