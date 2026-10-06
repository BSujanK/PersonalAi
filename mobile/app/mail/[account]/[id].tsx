import { useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { Text } from 'react-native';

import { Screen } from '../../../src/components/Screen';
import { Body, Caption, Card, ErrorText, Loading, SectionTitle } from '../../../src/components/ui';
import { getMailMessage, type MailAddress, type MailMessage } from '../../../src/lib/api';
import { errorMessage, formatBytes, shortDateTime } from '../../../src/lib/format';
import { fontFamily, size, useThemedStyles, type Palette } from '../../../src/theme';

const makeStyles = (p: Palette) => ({
  subject: { fontFamily: fontFamily.bodySemiBold, fontSize: size.body + 2, color: p.text },
  // Plain text only: the body is never rendered as HTML or markdown and links are not detected.
  bodyText: { fontFamily: fontFamily.body, fontSize: size.body, lineHeight: 23, color: p.text },
});

const person = ({ name, addr }: MailAddress) => (name ? `${name} <${addr}>` : addr);
const people = (list: MailAddress[]) => list.map(person).join(', ');

/** One mail, read-only: headers, attachment metadata and the plain-text body. */
export default function MailDetail() {
  const styles = useThemedStyles(makeStyles);
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

  return (
    <Screen
      title="Mail"
      back
      refreshing={false}
      onRefresh={() => setReloadKey((k) => k + 1)}
    >
      <ErrorText message={error} />
      {!mail && !error ? <Loading /> : null}
      {mail ? (
        <>
          <Card>
            <Text selectable style={styles.subject}>
              {mail.subject || '(no subject)'}
            </Text>
            <Body muted>From: {person(mail.from)}</Body>
            {mail.to.length > 0 ? <Body muted>To: {people(mail.to)}</Body> : null}
            {mail.cc.length > 0 ? <Body muted>Cc: {people(mail.cc)}</Body> : null}
            <Body muted>{shortDateTime(mail.date)}</Body>
            {mail.category ? (
              <Body muted>
                {mail.category}
                {mail.reason ? ` - ${mail.reason}` : ''}
              </Body>
            ) : null}
            {mail.labels.length > 0 ? <Caption>Labels: {mail.labels.join(', ')}</Caption> : null}
          </Card>

          {mail.source === 'stored' ? (
            <Body muted>Showing the saved copy; Gmail could not be reached.</Body>
          ) : null}

          {mail.attachments.length > 0 ? (
            <>
              <SectionTitle>Attachments</SectionTitle>
              {mail.attachments.map((a, i) => (
                <Card key={`${a.name}:${i}`}>
                  <Body>{a.name}</Body>
                  <Caption>
                    {formatBytes(a.size)} - {a.mime}
                  </Caption>
                </Card>
              ))}
            </>
          ) : null}

          <Text selectable style={styles.bodyText}>
            {mail.body}
          </Text>
          {mail.body_truncated ? (
            <Body muted>This message is long, so only the first part is shown.</Body>
          ) : null}
        </>
      ) : null}
    </Screen>
  );
}
