import { useCallback, useState } from 'react';

import {
  Body,
  Card,
  ErrorText,
  Loading,
  Screen,
  SectionTitle,
  Title,
} from '../../src/components/ui';
import { ApiError, getToday, type Today } from '../../src/lib/api';
import { errorMessage, shortDateTime } from '../../src/lib/format';
import { usePolling } from '../../src/lib/usePolling';

const NOT_CONFIGURED = 'Not configured on the laptop yet.';

export default function TodayScreen() {
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
    <Screen refreshing={refreshing} onRefresh={() => void refresh()}>
      <Title>Today</Title>
      <ErrorText message={error} />
      {!today && !error ? <Loading /> : null}
      {today ? (
        <>
          <SectionTitle>Important mail</SectionTitle>
          {today.mail === null ? <Body muted>{NOT_CONFIGURED}</Body> : null}
          {today.mail && important.length === 0 ? <Body muted>Nothing important.</Body> : null}
          {important.map((mail) => (
            <Card key={`${mail.account}:${mail.id}`}>
              <Body>{mail.subject}</Body>
              <Body muted>{mail.from_name || mail.from_addr}</Body>
              {mail.reason ? <Body muted>{mail.reason}</Body> : null}
            </Card>
          ))}

          <SectionTitle>Deadlines</SectionTitle>
          {today.deadlines === null ? <Body muted>{NOT_CONFIGURED}</Body> : null}
          {today.deadlines?.length === 0 ? <Body muted>No upcoming deadlines.</Body> : null}
          {today.deadlines?.map((d, i) => (
            <Card key={`${d.course ?? ''}:${d.title ?? ''}:${i}`}>
              <Body>{String(d.title ?? '')}</Body>
              <Body muted>{[d.course, shortDateTime(d.due)].filter(Boolean).join(' - ')}</Body>
            </Card>
          ))}

          <SectionTitle>Events</SectionTitle>
          {today.events === null ? <Body muted>{NOT_CONFIGURED}</Body> : null}
          {today.events?.length === 0 ? <Body muted>No events.</Body> : null}
          {today.events?.map((e, i) => (
            <Card key={`${e.id ?? ''}:${i}`}>
              <Body>{String(e.summary ?? '')}</Body>
              <Body muted>{shortDateTime(e.start)}</Body>
              {e.location ? <Body muted>{String(e.location)}</Body> : null}
            </Card>
          ))}
        </>
      ) : null}
    </Screen>
  );
}
