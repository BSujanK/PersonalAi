import * as Clipboard from 'expo-clipboard';
import { memo, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Pressable, ScrollView, Text, View, type TextStyle } from 'react-native';

import { confirmOpen } from '../../lib/confirmLink';
import { attr, cellAlign, isSafeLink, parseMarkdown, type MdNode } from '../../lib/markdown';
import { fontFamily, MIN_TARGET, space, type, useThemedStyles, type Palette } from '../../theme';
import { Icon } from '../Icon';

// Headings in the display serif (Newsreader), kept modest so an answer reads as prose with
// signposts, not a poster: h1 23, h2 20, h3 18. h4 and below are the UI face, semibold.
const HEADING_STYLE: Record<string, TextStyle> = {
  h1: type.title2,
  h2: { ...type.title2, fontSize: 20, lineHeight: 26, letterSpacing: -0.25 },
  h3: { ...type.title2, fontSize: 18, lineHeight: 24, letterSpacing: -0.2 },
  h4: type.headline,
  h5: type.headline,
  h6: type.headline,
};
/** Bullets by nesting level: solid, hollow, square. */
const BULLETS = ['•', '◦', '▪'] as const;
const COPIED_MS = 1500;

const makeStyles = (p: Palette) => ({
  root: { gap: space.sm + space.xs },
  paragraph: { ...type.body, color: p.text, fontVariant: ['tabular-nums' as const] },
  heading: { color: p.text, marginTop: space.sm },
  strong: { fontFamily: fontFamily.bodySemiBold, fontWeight: 'normal' as const },
  em: { fontStyle: 'italic' as const },
  strike: { textDecorationLine: 'line-through' as const },
  link: { color: p.accentText, textDecorationLine: 'underline' as const },
  inlineCode: {
    fontFamily: fontFamily.mono,
    fontSize: type.callout.fontSize,
    backgroundColor: p.muted,
  },
  list: { gap: 6 },
  item: { flexDirection: 'row' as const, gap: 8 },
  // The marker shares the body's line height, so it sits on the first line's baseline and the
  // item text hangs to its right, including after it wraps.
  marker: {
    ...type.body,
    color: p.textMuted,
    minWidth: 22,
    textAlign: 'right' as const,
    fontVariant: ['tabular-nums' as const],
  },
  itemBody: { flex: 1, gap: 6 },
  quote: {
    borderLeftWidth: 3,
    borderLeftColor: p.accent,
    paddingLeft: space.sm + space.xs,
    gap: 8,
  },
  rule: { height: 1, backgroundColor: p.separator, marginVertical: space.sm },
  code: { backgroundColor: p.muted, borderRadius: 12, overflow: 'hidden' as const },
  codeBar: {
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    justifyContent: 'space-between' as const,
    paddingLeft: 12,
    borderBottomWidth: 1,
    borderBottomColor: p.border,
  },
  codeLang: { ...type.caption, color: p.textMuted },
  copy: {
    minHeight: MIN_TARGET,
    paddingHorizontal: 12,
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    gap: 6,
  },
  copyText: { ...type.caption, color: p.textMuted },
  codeText: {
    fontFamily: fontFamily.mono,
    fontSize: type.footnote.fontSize,
    lineHeight: 20,
    color: p.text,
    padding: 12,
  },
  table: {
    minWidth: '100%' as const,
    borderWidth: 1,
    borderColor: p.border,
    borderRadius: 10,
    overflow: 'hidden' as const,
  },
  row: { flexDirection: 'row' as const },
  rowHead: { backgroundColor: p.muted },
  cell: {
    flex: 1,
    minWidth: 104,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRightWidth: 1,
    borderBottomWidth: 1,
    borderColor: p.border,
  },
  cellText: { ...type.subheadline, color: p.text, fontVariant: ['tabular-nums' as const] },
  cellHead: { fontFamily: fontFamily.bodySemiBold },
});

type Styles = ReturnType<typeof useStyles>;
const useStyles = () => useThemedStyles(makeStyles);

function renderInline(nodes: MdNode[], styles: Styles, keyPrefix = 'i'): ReactNode[] {
  return nodes.map((node, index) => {
    const key = `${keyPrefix}${index}`;
    switch (node.type) {
      case 'text':
        return node.token.content;
      case 'softbreak':
      case 'hardbreak':
        return '\n';
      case 'code_inline':
        return (
          <Text key={key} style={styles.inlineCode}>
            {node.token.content}
          </Text>
        );
      case 'strong':
        return (
          <Text key={key} style={styles.strong}>
            {renderInline(node.children, styles, key)}
          </Text>
        );
      case 'em':
        return (
          <Text key={key} style={styles.em}>
            {renderInline(node.children, styles, key)}
          </Text>
        );
      case 's':
        return (
          <Text key={key} style={styles.strike}>
            {renderInline(node.children, styles, key)}
          </Text>
        );
      case 'link': {
        const href = attr(node.token, 'href');
        const label = renderInline(node.children, styles, key);
        if (!isSafeLink(href)) return <Text key={key}>{label}</Text>;
        return (
          <Text
            key={key}
            accessibilityRole="link"
            style={styles.link}
            onPress={() => confirmOpen(href)}
          >
            {label}
          </Text>
        );
      }
      case 'image':
        // Never fetched: an image URL in model text could leak data just by loading.
        return `[image: ${node.token.content || 'omitted'}]`;
      default:
        return node.children.length > 0 ? renderInline(node.children, styles, key) : null;
    }
  });
}

export function CodeBlock({ code, language }: { code: string; language: string }) {
  const styles = useStyles();
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);

  async function copy() {
    await Clipboard.setStringAsync(code);
    setCopied(true);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), COPIED_MS);
  }

  return (
    <View style={styles.code}>
      <View style={styles.codeBar}>
        <Text style={styles.codeLang}>{language || 'code'}</Text>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={copied ? 'Copied' : 'Copy code'}
          onPress={() => void copy()}
          style={styles.copy}
        >
          <Icon name={copied ? 'check' : 'copy'} size={16} />
          <Text style={styles.copyText}>{copied ? 'Copied' : 'Copy'}</Text>
        </Pressable>
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false}>
        <Text selectable style={styles.codeText}>
          {code.replace(/\n$/, '')}
        </Text>
      </ScrollView>
    </View>
  );
}

function renderTable(node: MdNode, styles: Styles, key: string): ReactNode {
  const rows: { head: boolean; cells: MdNode[] }[] = [];
  for (const section of node.children) {
    for (const tr of section.children) {
      rows.push({ head: section.type === 'thead', cells: tr.children });
    }
  }
  return (
    <ScrollView
      key={key}
      testID="md-table"
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={{ minWidth: '100%' }}
    >
      <View style={styles.table}>
        {rows.map((row, r) => (
          <View key={`r${r}`} style={[styles.row, row.head && styles.rowHead]}>
            {row.cells.map((cell, c) => (
              <View key={`c${c}`} style={styles.cell}>
                <Text
                  selectable
                  style={[
                    styles.cellText,
                    row.head && styles.cellHead,
                    { textAlign: cellAlign(cell.token) },
                  ]}
                >
                  {renderInline(cell.children[0]?.children ?? [], styles, `t${r}${c}`)}
                </Text>
              </View>
            ))}
          </View>
        ))}
      </View>
    </ScrollView>
  );
}

function renderBlocks(nodes: MdNode[], styles: Styles, keyPrefix = 'b', depth = 0): ReactNode[] {
  return nodes.map((node, index) => {
    const key = `${keyPrefix}${index}`;
    switch (node.type) {
      case 'paragraph': {
        return (
          <Text key={key} selectable style={styles.paragraph}>
            {renderInline(node.children[0]?.children ?? [], styles)}
          </Text>
        );
      }
      case 'heading': {
        const tag = node.token.tag;
        return (
          <Text
            key={key}
            accessibilityRole="header"
            selectable
            style={[HEADING_STYLE[tag] ?? type.headline, styles.heading]}
          >
            {renderInline(node.children[0]?.children ?? [], styles)}
          </Text>
        );
      }
      case 'bullet_list':
      case 'ordered_list': {
        const ordered = node.type === 'ordered_list';
        const start = Number(attr(node.token, 'start') ?? 1);
        return (
          <View key={key} style={styles.list}>
            {node.children.map((item, i) => (
              <View key={`${key}-${i}`} style={styles.item}>
                <Text style={styles.marker}>
                  {ordered ? `${start + i}.` : BULLETS[Math.min(depth, BULLETS.length - 1)]}
                </Text>
                <View style={styles.itemBody}>
                  {renderBlocks(item.children, styles, `${key}-${i}-`, depth + 1)}
                </View>
              </View>
            ))}
          </View>
        );
      }
      case 'blockquote':
        return (
          <View key={key} testID="md-quote" style={styles.quote}>
            {renderBlocks(node.children, styles, `${key}-`, depth)}
          </View>
        );
      case 'fence':
      case 'code_block':
        return (
          <CodeBlock
            key={key}
            code={node.token.content}
            language={node.type === 'fence' ? node.token.info.trim().split(/\s+/)[0] : ''}
          />
        );
      case 'hr':
        return <View key={key} testID="md-rule" style={styles.rule} />;
      case 'table':
        return renderTable(node, styles, key);
      default:
        return null;
    }
  });
}

/** Renders a markdown reply: headings, lists, emphasis, links, tables and fenced code. */
function MarkdownImpl({ text }: { text: string }) {
  const styles = useStyles();
  const tree = useMemo(() => parseMarkdown(text), [text]);
  return <View style={styles.root}>{renderBlocks(tree, styles)}</View>;
}

export const Markdown = memo(MarkdownImpl);
