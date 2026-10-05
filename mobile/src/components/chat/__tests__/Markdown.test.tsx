import { fireEvent, render, screen } from '@testing-library/react-native';
import * as Clipboard from 'expo-clipboard';
import { Alert, Linking } from 'react-native';

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
