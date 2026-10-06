// Grouping for the "All mail" list on Today: inbox pages under category headers.
import type { InboxCategory, InboxItem } from './api';

export const GROUPS: readonly { category: InboxCategory; title: string }[] = [
  { category: 'important', title: 'Important' },
  { category: 'normal', title: 'Normal' },
  { category: 'unclassified', title: 'Unclassified' },
  { category: 'promo', title: 'Promotions' },
  { category: 'spam', title: 'Spam' },
];

export interface InboxGroup {
  category: InboxCategory;
  title: string;
  /** Messages of this category in the whole mailbox, not just the ones loaded so far. */
  count: number;
  items: InboxItem[];
}

export const mailKey = (mail: { account: string; id: string }): string =>
  `${mail.account}:${mail.id}`;

/** Append a page, dropping messages that are already loaded (pages can overlap after new mail). */
export function appendPage(loaded: readonly InboxItem[], page: readonly InboxItem[]): InboxItem[] {
  const seen = new Set(loaded.map(mailKey));
  const added: InboxItem[] = [];
  for (const item of page) {
    if (seen.has(mailKey(item))) continue;
    seen.add(mailKey(item));
    added.push(item);
  }
  return [...loaded, ...added];
}

/**
 * Group loaded messages by category in display order. Messages in `skip` (the Important list
 * shown above) and repeated messages are left out; groups with nothing to show are omitted.
 */
export function groupInbox(
  items: readonly InboxItem[],
  counts: Partial<Record<InboxCategory, number>>,
  skip: ReadonlySet<string> = new Set(),
): InboxGroup[] {
  const seen = new Set(skip);
  const byCategory = new Map<InboxCategory, InboxItem[]>();
  for (const item of items) {
    const key = mailKey(item);
    if (seen.has(key)) continue;
    seen.add(key);
    const category: InboxCategory = item.category ?? 'unclassified';
    byCategory.set(category, [...(byCategory.get(category) ?? []), item]);
  }
  return GROUPS.flatMap(({ category, title }) => {
    const grouped = byCategory.get(category);
    return grouped
      ? [{ category, title, count: counts[category] ?? grouped.length, items: grouped }]
      : [];
  });
}
