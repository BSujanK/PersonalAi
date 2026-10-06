import { useRouter } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { Screen } from '../../src/components/Screen';
import { Badge, EmptyRow, ErrorText, ListRow, ListSection, Loading } from '../../src/components/ui';
import { askAboutDeadline, askAboutEvent } from '../../src/lib/agentPrompts';
import { ApiError, getToday, type DigestItem, type Today } from '../../src/lib/api';
import { openNewChat } from '../../src/lib/chatRoutes';
import { errorMessage, initials, longDate, rowTime, shortDateTime } from '../../src/lib/format';
import { usePolling } from '../../src/lib/usePolling';
import {
  fontFamily,
  MIN_TARGET,
  ROW_INSET,
  space,
  type,
  useTheme,
  useThemedStyles,
  type Palette,
} from '../../src/theme';

const NOT_CONFIGURED = 'Not configured on the laptop yet.';
const AVATAR = 40;
/** Mail row hairlines start under the text, after the avatar. */
const MAIL_INSET = ROW_INSET + AVATAR + space.md - space.xs;

const makeStyles = (p: Palette) => ({
  mailRow: {
    minHeight: MIN_TARGET + 4,
    flexDirection: 'row' as const,
    gap: space.md - space.xs,
    paddingHorizontal: ROW_INSET,
    paddingVertical: space.sm + space.xs,
    backgroundColor: p.surface,
  },
  mailRowPressed: { backgroundColor: p.muted },
  avatar: {
    width: AVATAR,
    height: AVATAR,
    borderRadius: AVATAR / 2,
    backgroundColor: p.accentSoft,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
  },
  avatarText: { ...type.subhead, fontFamily: fontFamily.bodySemiBold, color: p.accentText },
  mailMain: { flex: 1, gap: 2 },
  mailTop: { flexDirection: 'row' as const, alignItems: 'baseline' as const, gap: space.sm },
  sender: { ...type.headline, color: p.text, flex: 1 },
  time: { ...type.footnote, color: p.textMuted },
  subject: { ...type.subhead, fontFamily: fontFamily.bodyMedium, color: p.text },
  snippet: { ...type.subhead, color: p.textMuted },
  reason: { marginTop: space.xs },
});

function MailRow({ mail, onPress }: { mail: DigestItem; onPress: () => void }) {
  const styles = useThemedStyles(makeStyles);
  const sender = mail.from_name || mail.from_addr;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`Mail from ${sender}: ${mail.subject}. ${rowTime(mail.received)}`}
      accessibilityHint="Opens the full message"
      onPress={onPress}
      pressRetentionOffset={16}
      style={({ pressed }) => [styles.mailRow, pressed && styles.mailRowPressed]}
    >
      <View style={styles.avatar}>
        <Text style={styles.avatarText} maxFontSizeMultiplier={1.3}>
          {initials(sender)}
        </Text>
      </View>
      <View style={styles.mailMain}>
        <View style={styles.mailTop}>
          <Text numberOfLines={1} style={styles.sender}>
            {sender}
          </Text>
          <Text style={styles.time}>{rowTime(mail.received)}</Text>
        </View>
        <Text numberOfLines={1} style={styles.subject}>
          {mail.subject || '(no subject)'}
        </Text>
        {mail.snippet ? (
          <Text numberOfLines={2} style={styles.snippet}>
            {mail.snippet}
          </Text>
        ) : null}
        {mail.reason ? (
          <View style={styles.reason}>
            <Badge label={mail.reason} tone="accent" />
          </View>
        ) : null}
      </View>
    </Pressable>
  );
}

export default function TodayScreen() {
  const router = useRouter();
  const { palette } = useTheme();
  const [today, setToday] = useState<Today | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setToday(await getToday());
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError && e.status === 404 ? NOT_CONFIGURED : errorMessage(e));
    }
  }, []);

  usePolling(load);

  async function refresh() {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }

  const important = today?.mail?.important ?? [];

  return (
    <Screen
      title="Today"
      subtitle={longDate()}
      menu
      refreshing={refreshing}
      onRefresh={() => void refresh()}
    >
      <ErrorText message={error} />
      {!today && !error ? <Loading /> : null}
      {today ? (
        <>
          <ListSection title="Important mail" inset={MAIL_INSET}>
            {today.mail === null ? <EmptyRow>{NOT_CONFIGURED}</EmptyRow> : null}
            {today.mail && important.length === 0 ? (
              <EmptyRow>Nothing important. Enjoy the quiet.</EmptyRow>
            ) : null}
            {important.map((mail) => (
              <MailRow
                key={`${mail.account}:${mail.id}`}
                mail={mail}
                onPress={() =>
                  router.push({
                    pathname: '/mail/[account]/[id]',
                    params: { account: mail.account, id: mail.id },
                  })
                }
              />
            ))}
          </ListSection>

          <ListSection
            title="Deadlines"
            inset="icon"
            footer={today.deadlines?.length ? 'Tap one to ask the agent about it.' : undefined}
          >
            {today.deadlines === null ? <EmptyRow>{NOT_CONFIGURED}</EmptyRow> : null}
            {today.deadlines?.length === 0 ? <EmptyRow>No upcoming deadlines.</EmptyRow> : null}
            {today.deadlines?.map((d, i) => (
              <ListRow
                key={`${d.course ?? ''}:${d.title ?? ''}:${i}`}
                icon="flag"
                iconTint={palette.warn}
                title={String(d.title ?? '')}
                subtitle={[d.course, shortDateTime(d.due)].filter(Boolean).join(' · ')}
                chevron
                accessibilityHint="Asks the agent about this deadline"
                onPress={() => openNewChat(router, askAboutDeadline(d))}
              />
            ))}
          </ListSection>

          <ListSection title="Events" inset="icon">
            {today.events === null ? <EmptyRow>{NOT_CONFIGURED}</EmptyRow> : null}
            {today.events?.length === 0 ? <EmptyRow>No events.</EmptyRow> : null}
            {today.events?.map((e, i) => (
              <ListRow
                key={`${e.id ?? ''}:${i}`}
                icon="calendar"
                title={String(e.summary ?? '')}
                subtitle={[shortDateTime(e.start), e.location].filter(Boolean).join(' · ')}
                chevron
                accessibilityHint="Asks the agent about this event"
                onPress={() => openNewChat(router, askAboutEvent(e))}
              />
            ))}
          </ListSection>
        </>
      ) : null}
    </Screen>
  );
}
