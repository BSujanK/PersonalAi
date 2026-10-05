// Markdown to a small tree. markdown-it does the parsing (CommonMark plus tables and
// strikethrough). Raw HTML is switched off, so HTML in a reply is shown as text, never rendered.
import MarkdownIt, { type Token } from 'markdown-it';

const parser = new MarkdownIt({ html: false, linkify: false, breaks: true, typographer: false });

// Images, scripts and other schemes are never loaded or opened from model text.
const SAFE_LINK = /^(https?:\/\/|mailto:)/i;

export function isSafeLink(href: string | null | undefined): href is string {
  return typeof href === 'string' && SAFE_LINK.test(href.trim());
}

export interface MdNode {
  type: string;
  token: Token;
  children: MdNode[];
}

/** Turn markdown-it's flat open/close token stream into a tree. Inline tokens get children too. */
export function buildTree(tokens: Token[]): MdNode[] {
  const root: MdNode = { type: 'root', token: undefined as unknown as Token, children: [] };
  const stack: MdNode[] = [root];
  for (const token of tokens) {
    const top = stack[stack.length - 1];
    if (token.nesting === 1) {
      const node: MdNode = { type: token.type.replace(/_open$/, ''), token, children: [] };
      top.children.push(node);
      stack.push(node);
    } else if (token.nesting === -1) {
      if (stack.length > 1) stack.pop();
    } else {
      const node: MdNode = {
        type: token.type,
        token,
        children: token.type === 'inline' && token.children ? buildTree(token.children) : [],
      };
      top.children.push(node);
    }
  }
  return root.children;
}

export function parseMarkdown(text: string): MdNode[] {
  return buildTree(parser.parse(text, {}));
}

export function attr(token: Token, name: string): string | null {
  const value = token.attrGet(name);
  return value === null ? null : String(value);
}

/** Column alignment markdown-it records on th/td as style="text-align:right". */
export function cellAlign(token: Token): 'left' | 'center' | 'right' {
  const style = attr(token, 'style') ?? '';
  if (style.includes('right')) return 'right';
  if (style.includes('center')) return 'center';
  return 'left';
}

/** Plain text of a node, for accessibility labels and copying. */
export function plainText(nodes: MdNode[]): string {
  return nodes
    .map((node) => {
      if (node.type === 'text' || node.type === 'code_inline') return node.token.content;
      if (node.type === 'softbreak' || node.type === 'hardbreak') return '\n';
      return plainText(node.children);
    })
    .join('');
}
