import { useRouter } from 'expo-router';
import { useCallback, useMemo, useState } from 'react';

import { MailCard } from '../src/components/MailCard';
import { Screen } from '../src/components/Screen';
import { Button, EmptyRow, ErrorText, ListSection, Loading } from '../src/components/ui';
import { useAccountLabels } from '../src/lib/accountLabels';
import { ApiError, getInbox, type InboxCategory, type InboxItem } from '../src/lib/api';
import { errorMessage } from '../src/lib/format';
import { appendPage, groupInbox, mailKey } from '../src/lib/inbox';
import { usePolling } from '../src/lib/usePolling';

const INBOX_PAGE = 50;

interface Inbox {
  items: InboxItem[];
  counts: Record<InboxCategory, number>;
  next: string | null;
  /** Pages loaded by "Load more", beyond the first. */
  extraPages: number;
}

/** Every synced mail, grouped by category, 50 at a time. Opened from "See all mail" on Today. */
export default function InboxScreen() {
  const router = useRouter();
  const labelFor = useAccountLabels();
  const [inbox, setInbox] = useState<Inbox | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  const load = useCallback(async () => {
    try {
      const page = await getInbox({ limit: INBOX_PAGE });
      setError(null);
      // A refresh keeps pages the owner already loaded, and their "Load more" position.
      setInbox((prev) =>
        prev && prev.extraPages > 0
          ? { ...prev, items: appendPage(page.items, prev.items), counts: page.counts }
          : { items: page.items, counts: page.counts, next: page.next_cursor, extraPages: 0 },
      );
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 404
          ? 'This agent cannot list the inbox yet. Update it on the laptop.'
          : errorMessage(e),
      );
    }
  }, []);

  usePolling(load);

  async function loadMore() {
    if (!inbox?.next || loadingMore) return;
    setLoadingMore(true);
    try {
      const page = await getInbox({ cursor: inbox.next, limit: INBOX_PAGE });
      setInbox({
        items: appendPage(inbox.items, page.items),
        counts: page.counts,
        next: page.next_cursor,
        extraPages: inbox.extraPages + 1,
      });
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoadingMore(false);
    }
  }

  async function refresh() {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }

  const groups = useMemo(() => groupInbox(inbox?.items ?? [], inbox?.counts ?? {}), [inbox]);
  const openMail = (mail: { account: string; id: string }) =>
    router.push({
      pathname: '/mail/[account]/[id]',
      params: { account: mail.account, id: mail.id },
    });

  return (
    <Screen title="All mail" back refreshing={refreshing} onRefresh={() => void refresh()}>
      <ErrorText message={error} />
      {!inbox && !error ? <Loading /> : null}
      {inbox && groups.length === 0 ? <EmptyRow>No mail synced yet.</EmptyRow> : null}
      {groups.map((group) => (
        <ListSection key={group.category} title={`${group.title} (${group.count})`}>
          {group.items.map((mail) => (
            <MailCard
              key={mailKey(mail)}
              mail={mail}
              accountLabel={labelFor(mail.account)}
              unread={mail.unread}
              onPress={() => openMail(mail)}
            />
          ))}
        </ListSection>
      ))}
      {inbox?.next ? (
        <Button
          label={loadingMore ? 'Loading…' : 'Load more'}
          tone="tinted"
          disabled={loadingMore}
          onPress={() => void loadMore()}
        />
      ) : null}
    </Screen>
  );
}
