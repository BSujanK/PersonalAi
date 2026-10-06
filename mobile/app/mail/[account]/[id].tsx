import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { Text, View } from 'react-native';

import { Icon, type IconName } from '../../../src/components/Icon';
import { Screen } from '../../../src/components/Screen';
import {
  Badge,
  Button,
  Card,
  ErrorText,
  ListRow,
  ListSection,
  Loading,
  Notice,
} from '../../../src/components/ui';
import { askAboutMail, mailRef, replyToMail } from '../../../src/lib/agentPrompts';
import { getMailMessage, type MailAddress, type MailMessage } from '../../../src/lib/api';
import { openNewChat } from '../../../src/lib/chatRoutes';
import { errorMessage, formatBytes, initials, shortDateTime } from '../../../src/lib/format';
import {
  fontFamily,
  radius,
  space,
  type,
  useTheme,
  useThemedStyles,
  type Palette,
} from '../../../src/theme';

const makeStyles = (p: Palette) => ({
  header: { gap: space.md, padding: space.md },
  subject: { ...type.title2, color: p.text },
  sender: {
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    gap: space.md - space.xs,
  },
  avatar: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: p.accentSoft,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
  },
  avatarText: { ...type.headline, color: p.accentText },
  senderMain: { flex: 1, gap: 2 },
  senderName: { ...type.headline, color: p.text },
  senderAddr: { ...type.subhead, color: p.textMuted },
  date: { ...type.footnote, color: p.textMuted },
  people: { gap: space.xs },
  peopleLine: { ...type.subhead, color: p.textMuted },
  peopleLabel: { fontFamily: fontFamily.bodySemiBold, color: p.text },
  tags: { flexDirection: 'row' as const, flexWrap: 'wrap' as const, gap: space.sm },
  // Side by side when they fit, stacked at large text sizes or on narrow phones.
  actions: { flexDirection: 'row' as const, flexWrap: 'wrap' as const, gap: space.sm },
  action: { flexGrow: 1, flexBasis: 140 },
  bodyCard: {
    backgroundColor: p.surface,
    borderRadius: radius.card,
    borderWidth: 1,
    borderColor: p.glassBorder,
    padding: space.md,
  },
  // Plain text only: the body is never rendered as HTML or markdown, links are not detected, and
  // nothing remote (images, trackers) is ever loaded.
  bodyText: { ...type.body, color: p.text },
  note: { ...type.footnote, color: p.textMuted, paddingHorizontal: space.md },
});

const person = ({ name, addr }: MailAddress) => (name ? `${name} <${addr}>` : addr);
const people = (list: MailAddress[]) => list.map(person).join(', ');

function attachmentIcon(mime: string): IconName {
  if (mime.startsWith('image/')) return 'image';
  if (mime.startsWith('text/') || mime.includes('pdf') || mime.includes('document')) {
    return 'file-text';
  }
  if (mime.includes('zip') || mime.includes('compressed')) return 'archive';
  return 'file';
}

/** One mail, read-only: headers, attachment metadata and the plain-text body. */
export default function MailDetail() {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  const router = useRouter();
  const { account, id } = useLocalSearchParams<{ account: string; id: string }>();
  const [mail, setMail] = useState<MailMessage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!account || !id) return;
    let cancelled = false;
    getMailMessage(account, id).then(
      (item) => {
        if (cancelled) return;
        setMail(item);
        setError(null);
      },
      (e: unknown) => {
        if (!cancelled) setError(errorMessage(e));
      },
    );
    return () => {
      cancelled = true;
    };
  }, [account, id, reloadKey]);

  const senderName = mail ? mail.from.name || mail.from.addr : '';

  return (
    <Screen back refreshing={false} onRefresh={() => setReloadKey((k) => k + 1)}>
      <ErrorText message={error} />
      {!mail && !error ? <Loading /> : null}
      {mail ? (
        <>
          <Card style={styles.header}>
            <Text selectable accessibilityRole="header" style={styles.subject}>
              {mail.subject || '(no subject)'}
            </Text>
            <View
              style={styles.sender}
              accessible
              accessibilityLabel={`From ${person(mail.from)}, ${shortDateTime(mail.date)}`}
            >
              <View style={styles.avatar}>
                <Text style={styles.avatarText} maxFontSizeMultiplier={1.3}>
                  {initials(senderName)}
                </Text>
              </View>
              <View style={styles.senderMain}>
                <Text style={styles.senderName}>{senderName}</Text>
                {mail.from.name ? (
                  <Text selectable style={styles.senderAddr}>
                    {mail.from.addr}
                  </Text>
                ) : null}
                <Text style={styles.date}>{shortDateTime(mail.date)}</Text>
              </View>
            </View>
            <View style={styles.people}>
              {mail.to.length > 0 ? (
                <Text selectable style={styles.peopleLine}>
                  <Text style={styles.peopleLabel}>To </Text>
                  {people(mail.to)}
                </Text>
              ) : null}
              {mail.cc.length > 0 ? (
                <Text selectable style={styles.peopleLine}>
                  <Text style={styles.peopleLabel}>Cc </Text>
                  {people(mail.cc)}
                </Text>
              ) : null}
            </View>
            {mail.category || mail.labels.length > 0 ? (
              <View style={styles.tags}>
                {mail.category ? (
                  <Badge
                    label={mail.reason ? `${mail.category} · ${mail.reason}` : mail.category}
                    tone="accent"
                  />
                ) : null}
                {mail.labels.map((label) => (
                  <Badge key={label} label={label} tone="neutral" />
                ))}
              </View>
            ) : null}
            <View style={styles.actions}>
              <View style={styles.action}>
                <Button
                  label="Reply"
                  icon="corner-up-left"
                  tone="primary"
                  compact
                  accessibilityHint="Starts a chat asking the agent to draft a reply. Nothing is sent without your approval."
                  onPress={() => openNewChat(router, replyToMail(mailRef(mail)))}
                />
              </View>
              <View style={styles.action}>
                <Button
                  label="Ask agent about this"
                  icon="message-circle"
                  tone="plain"
                  compact
                  accessibilityHint="Starts a chat about this email"
                  onPress={() => openNewChat(router, askAboutMail(mailRef(mail)))}
                />
              </View>
            </View>
          </Card>

          {mail.source === 'stored' ? (
            <Notice tone="warn">Showing the saved copy; Gmail could not be reached.</Notice>
          ) : null}

          {mail.attachments.length > 0 ? (
            <ListSection
              title={`${mail.attachments.length} attachment${mail.attachments.length === 1 ? '' : 's'}`}
            >
              {mail.attachments.map((a, i) => (
                <ListRow
                  key={`${a.name}:${i}`}
                  icon={attachmentIcon(a.mime)}
                  iconTint={palette.textMuted}
                  title={a.name}
                  subtitle={`${formatBytes(a.size)} · ${a.mime}`}
                  accessibilityLabel={`Attachment ${a.name}, ${formatBytes(a.size)}`}
                />
              ))}
            </ListSection>
          ) : null}

          <View style={styles.bodyCard}>
            <Text selectable style={styles.bodyText}>
              {mail.body}
            </Text>
          </View>
          {mail.body_truncated ? (
            <Text style={styles.note}>This message is long, so only the first part is shown.</Text>
          ) : null}
          <View style={[styles.tags, { justifyContent: 'center' }]}>
            <Icon name="shield" size={14} color={palette.textMuted} />
            <Text style={styles.date}>Plain text only. Images and links are never loaded.</Text>
          </View>
        </>
      ) : null}
    </Screen>
  );
}
