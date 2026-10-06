import { useRouter } from 'expo-router';
import { useMemo, useState } from 'react';

import { MailCard } from '../src/components/MailCard';
import { Screen } from '../src/components/Screen';
import { SkeletonRows } from '../src/components/Skeleton';
import {
  Button,
  EmptyRow,
  ErrorText,
  ListSection,
  LoadFailed,
  StaleNote,
} from '../src/components/ui';
import { useAccountLabels } from '../src/lib/accountLabels';
import { ApiError, getInbox, type InboxItem } from '../src/lib/api';
import { errorMessage } from '../src/lib/format';
import { appendPage, groupInbox, mailKey } from '../src/lib/inbox';
import { useLoader, usePullToRefresh } from '../src/lib/usePolling';

const INBOX_PAGE = 50;

const fetchFirstPage = () => getInbox({ limit: INBOX_PAGE });

/** Every synced mail, grouped by category, 50 at a time. Opened from "See all mail" on Today. */
export default function InboxScreen() {
  const router = useRouter();
  const labelFor = useAccountLabels();
  const { data: page, error, loading, failing, retrying, reload } = useLoader(fetchFirstPage);
  const pull = usePullToRefresh(reload);
  // Everything shown once "Load more" was used, and where the next page starts.
  const [more, setMore] = useState<{ items: InboxItem[]; next: string | null } | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState<string | null>(null);

  // A refresh puts the fresh first page on top of what was loaded, so nothing already shown drops
  // off and the "Load more" position stays.
  const [seen, setSeen] = useState(page);
  if (page !== seen) {
    setSeen(page);
    if (page) setMore((prev) => prev && { ...prev, items: appendPage(page.items, prev.items) });
  }

  const items = useMemo(() => more?.items ?? page?.items ?? [], [more, page]);
  const next = more ? more.next : (page?.next_cursor ?? null);

  async function loadMore() {
    if (!next || loadingMore) return;
    setLoadingMore(true);
    try {
      const nextPage = await getInbox({ cursor: next, limit: INBOX_PAGE });
      setMore({ items: appendPage(items, nextPage.items), next: nextPage.next_cursor });
      setMoreError(null);
    } catch (e) {
      setMoreError(errorMessage(e));
    } finally {
      setLoadingMore(false);
    }
  }

  const groups = useMemo(() => groupInbox(items, page?.counts ?? {}), [items, page]);
  const openMail = (mail: { account: string; id: string }) =>
    router.push({
      pathname: '/mail/[account]/[id]',
      params: { account: mail.account, id: mail.id },
    });

  return (
    <Screen title="All mail" back {...pull}>
      <ErrorText message={moreError} />
      {failing && page ? <StaleNote /> : null}
      {failing && !page ? (
        <LoadFailed
          what="your mail"
          reason={
            error instanceof ApiError && error.status === 404
              ? 'This agent cannot list the inbox yet. Update it on the laptop.'
              : errorMessage(error)
          }
          retrying={retrying}
        />
      ) : null}
      {loading ? <SkeletonRows count={5} avatar /> : null}
      {page && groups.length === 0 ? <EmptyRow>No mail synced yet.</EmptyRow> : null}
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
      {next ? (
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
