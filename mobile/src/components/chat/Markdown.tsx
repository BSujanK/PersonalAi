import * as Clipboard from 'expo-clipboard';
import { memo, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Alert, Linking, Pressable, ScrollView, Text, View } from 'react-native';

import { attr, cellAlign, isSafeLink, parseMarkdown, type MdNode } from '../../lib/markdown';
import { fontFamily, MIN_TARGET, size, useThemedStyles, type Palette } from '../../theme';
import { Icon } from '../Icon';

const HEADING_SIZE: Record<string, number> = { h1: 24, h2: 21, h3: 18, h4: 16, h5: 16, h6: 16 };
const COPIED_MS = 1500;

const makeStyles = (p: Palette) => ({
  root: { gap: 10 },
  paragraph: { fontFamily: fontFamily.body, fontSize: size.body, lineHeight: 25, color: p.text },
  heading: { fontFamily: fontFamily.display, color: p.text, marginTop: 6 },
  headingSmall: { fontFamily: fontFamily.bodySemiBold },
  strong: { fontFamily: fontFamily.bodySemiBold, fontWeight: 'normal' as const },
  em: { fontStyle: 'italic' as const },
  strike: { textDecorationLine: 'line-through' as const },
  link: { color: p.accent, textDecorationLine: 'underline' as const },
  inlineCode: {
    fontFamily: fontFamily.mono,
    fontSize: size.body - 2,
    backgroundColor: p.muted,
  },
  list: { gap: 6 },
  item: { flexDirection: 'row' as const, gap: 8 },
  marker: {
    fontFamily: fontFamily.body,
    fontSize: size.body,
    lineHeight: 25,
    color: p.textMuted,
    minWidth: 20,
    textAlign: 'right' as const,
  },
  itemBody: { flex: 1, gap: 6 },
  quote: { borderLeftWidth: 3, borderLeftColor: p.border, paddingLeft: 12, gap: 8 },
  rule: { height: 1, backgroundColor: p.border, marginVertical: 6 },
  code: { backgroundColor: p.muted, borderRadius: 12, overflow: 'hidden' as const },
  codeBar: {
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    justifyContent: 'space-between' as const,
    paddingLeft: 12,
    borderBottomWidth: 1,
    borderBottomColor: p.border,
  },
  codeLang: { fontFamily: fontFamily.bodyMedium, fontSize: size.caption, color: p.textMuted },
  copy: {
    minHeight: MIN_TARGET,
    paddingHorizontal: 12,
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    gap: 6,
  },
  copyText: { fontFamily: fontFamily.bodyMedium, fontSize: size.caption + 1, color: p.textMuted },
  codeText: {
    fontFamily: fontFamily.mono,
    fontSize: size.small,
    lineHeight: 20,
    color: p.text,
    padding: 12,
  },
  table: { borderWidth: 1, borderColor: p.border, borderRadius: 10, overflow: 'hidden' as const },
  row: { flexDirection: 'row' as const },
  rowHead: { backgroundColor: p.muted },
  cell: {
    width: 120,
    paddingHorizontal: 10,
    paddingVertical: 8,
    borderRightWidth: 1,
    borderBottomWidth: 1,
    borderColor: p.border,
  },
  cellText: { fontFamily: fontFamily.body, fontSize: size.small + 1, color: p.text },
  cellHead: { fontFamily: fontFamily.bodySemiBold },
});

type Styles = ReturnType<typeof useStyles>;
const useStyles = () => useThemedStyles(makeStyles);

function confirmOpen(href: string) {
  Alert.alert('Open link?', href, [
    { text: 'Cancel', style: 'cancel' },
    { text: 'Open', onPress: () => void Linking.openURL(href).catch(() => undefined) },
  ]);
}

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
    <ScrollView key={key} horizontal showsHorizontalScrollIndicator={false}>
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

function renderBlocks(nodes: MdNode[], styles: Styles, keyPrefix = 'b'): ReactNode[] {
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
        const small = tag === 'h4' || tag === 'h5' || tag === 'h6';
        return (
          <Text
            key={key}
            accessibilityRole="header"
            selectable
            style={[styles.heading, small && styles.headingSmall, { fontSize: HEADING_SIZE[tag] }]}
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
                <Text style={styles.marker}>{ordered ? `${start + i}.` : '•'}</Text>
                <View style={styles.itemBody}>
                  {renderBlocks(item.children, styles, `${key}-${i}-`)}
                </View>
              </View>
            ))}
          </View>
        );
      }
      case 'blockquote':
        return (
          <View key={key} style={styles.quote}>
            {renderBlocks(node.children, styles, `${key}-`)}
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
        return <View key={key} style={styles.rule} />;
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
