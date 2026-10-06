import { Text, View } from 'react-native';

import {
  parsePreview,
  type PreviewAttachment,
  type PreviewRecipient,
  type RecipientField,
} from '../../lib/actionPreview';
import {
  fontFamily,
  radius,
  space,
  type,
  useTheme,
  useThemedStyles,
  type Palette,
} from '../../theme';
import { Icon } from '../Icon';
import { Badge, Notice } from '../ui';

const makeStyles = (p: Palette) => ({
  root: { gap: space.md },
  block: { gap: space.sm },
  label: {
    ...type.footnote,
    fontFamily: fontFamily.bodySemiBold,
    letterSpacing: 0.4,
    textTransform: 'uppercase' as const,
    color: p.textMuted,
  },
  person: {
    flexDirection: 'row' as const,
    flexWrap: 'wrap' as const,
    alignItems: 'center' as const,
    gap: space.sm,
  },
  addr: { ...type.callout, color: p.text, flexShrink: 1 },
  fileRow: {
    flexDirection: 'row' as const,
    gap: space.sm + space.xs,
    alignItems: 'flex-start' as const,
  },
  fileIcon: {
    width: 32,
    height: 32,
    borderRadius: radius.sm,
    backgroundColor: p.muted,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
  },
  fileMain: { flex: 1, gap: 2 },
  fileName: { ...type.callout, fontFamily: fontFamily.bodyMedium, color: p.text },
  fileMeta: { ...type.footnote, color: p.textMuted },
  value: { ...type.callout, color: p.text },
  scope: { ...type.callout, fontFamily: fontFamily.bodySemiBold },
  well: { backgroundColor: p.muted, borderRadius: radius.md, padding: space.md - space.xs },
  exact: { fontFamily: fontFamily.mono, fontSize: 13, lineHeight: 19, color: p.text },
});

const FIELD_LABEL: Record<RecipientField, string> = {
  To: 'To',
  Cc: 'Cc',
  Bcc: 'Bcc',
  People: 'Shared with',
};

/** NEW and EXTERNAL badges for one recipient, spoken in full for screen readers. */
export function RecipientBadges({ recipient }: { recipient: PreviewRecipient }) {
  if (recipient.you) return <Badge label="YOU" tone="neutral" spoken="your own address" />;
  return (
    <>
      {recipient.isNew ? (
        <Badge label="NEW" tone="warn" spoken="new: you have never emailed this address" />
      ) : null}
      {recipient.external ? (
        <Badge label="EXTERNAL" tone="danger" spoken="external: outside your own domains" />
      ) : null}
    </>
  );
}

function Recipients({ list }: { list: PreviewRecipient[] }) {
  const styles = useThemedStyles(makeStyles);
  const fields = [...new Set(list.map((r) => r.field))];
  return (
    <>
      {fields.map((field) => (
        <View key={field} style={styles.block}>
          <Text style={styles.label}>{FIELD_LABEL[field]}</Text>
          {list
            .filter((r) => r.field === field)
            .map((r) => (
              <View key={`${field}:${r.addr}`} style={styles.person}>
                <Text selectable style={styles.addr}>
                  {r.addr}
                </Text>
                <RecipientBadges recipient={r} />
              </View>
            ))}
        </View>
      ))}
    </>
  );
}

function Attachments({ list, label }: { list: PreviewAttachment[]; label: string }) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  return (
    <View style={styles.block}>
      <Text style={styles.label}>{label}</Text>
      {list.map((a, i) => (
        <View
          key={`${a.name}:${i}`}
          style={styles.fileRow}
          accessible
          accessibilityLabel={`${a.name}, ${a.size}, from ${a.source === 'local' ? 'this laptop' : 'Google Drive'}: ${a.location}`}
        >
          <View style={styles.fileIcon}>
            <Icon
              name={a.source === 'local' ? 'hard-drive' : 'cloud'}
              size={16}
              color={palette.accentText}
            />
          </View>
          <View style={styles.fileMain}>
            <Text style={styles.fileName}>{a.name}</Text>
            <Text style={styles.fileMeta}>{[a.size, a.mime].filter(Boolean).join(' · ')}</Text>
            <Text selectable style={styles.fileMeta}>
              {a.source === 'local' ? `Laptop: ${a.location}` : a.location}
            </Text>
          </View>
        </View>
      ))}
    </View>
  );
}

/**
 * Structured view of a proposed action, then the exact preview text the server stored. The
 * structured part is read from that same text, so it can only ever repeat it.
 */
export function ActionPreview({ toolName, preview }: { toolName: string; preview: string }) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  const parsed = parsePreview(toolName, preview);
  const anyone = parsed.linkScope === 'anyone';
  return (
    <View style={styles.root}>
      {anyone ? (
        <Notice tone="danger" title="Anyone with the link can open this file">
          The link works without signing in and can be forwarded to anyone.
        </Notice>
      ) : null}

      {parsed.account ? (
        <View style={styles.block}>
          <Text style={styles.label}>{parsed.kind === 'mail' ? 'From' : 'Account'}</Text>
          <Text selectable style={styles.value}>
            {parsed.account}
          </Text>
        </View>
      ) : null}

      {parsed.recipients.length > 0 ? <Recipients list={parsed.recipients} /> : null}

      {parsed.subject !== null ? (
        <View style={styles.block}>
          <Text style={styles.label}>Subject</Text>
          <Text selectable style={styles.value}>
            {parsed.subject || '(no subject)'}
          </Text>
        </View>
      ) : null}

      {parsed.file ? (
        <View style={styles.block}>
          <Text style={styles.label}>File</Text>
          <Text selectable style={styles.value}>
            {parsed.file.name}
          </Text>
        </View>
      ) : null}

      {parsed.attachments.length > 0 ? (
        <Attachments
          list={parsed.attachments}
          label={parsed.kind === 'drive_upload' ? 'File' : 'Attachments'}
        />
      ) : null}

      {parsed.folder ? (
        <View style={styles.block}>
          <Text style={styles.label}>Upload to</Text>
          <Text style={styles.value}>{parsed.folder}</Text>
        </View>
      ) : null}

      {parsed.kind === 'drive_share' ? (
        <View style={styles.block}>
          <Text style={styles.label}>Access</Text>
          {parsed.access ? <Text style={styles.value}>{parsed.access}</Text> : null}
          <Text
            accessibilityLabel={
              anyone ? 'Link scope: anyone with the link' : 'Link scope: only the people listed'
            }
            style={[styles.scope, { color: anyone ? palette.danger : palette.text }]}
          >
            {anyone ? 'Anyone with the link' : 'Only the people listed'}
          </Text>
        </View>
      ) : null}

      <View style={styles.block}>
        <Text style={styles.label}>Full preview</Text>
        <View style={styles.well}>
          <Text selectable style={styles.exact}>
            {preview}
          </Text>
        </View>
      </View>
    </View>
  );
}
