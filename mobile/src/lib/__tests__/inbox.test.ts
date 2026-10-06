import type { InboxItem } from '../api';
import { appendPage, groupInbox, mailKey } from '../inbox';

function item(id: string, category: InboxItem['category'], account = 'main'): InboxItem {
  return {
    account,
    id,
    message_id: `msg-${id}`,
    thread_id: `t-${id}`,
    category,
    from_name: 'Asha Rao',
    from_addr: `asha_${id}`,
    subject: `Subject ${id}`,
    snippet: '',
    reason: null,
    received: '2026-10-06T04:00:00Z',
    unread: false,
  };
}

const counts = { important: 7, normal: 20, promo: 40, spam: 3, unclassified: 5 };

describe('groupInbox', () => {
  it('orders groups Important, Normal, Unclassified, Promotions, Spam with server counts', () => {
    const groups = groupInbox(
      [
        item('s', 'spam'),
        item('p', 'promo'),
        item('u', null),
        item('n', 'normal'),
        item('i', 'important'),
      ],
      counts,
    );
    expect(groups.map((g) => [g.title, g.count])).toEqual([
      ['Important', 7],
      ['Normal', 20],
      ['Unclassified', 5],
      ['Promotions', 40],
      ['Spam', 3],
    ]);
  });

  it('omits empty groups and falls back to the loaded count without a server count', () => {
    const groups = groupInbox([item('n1', 'normal'), item('n2', 'normal')], {});
    expect(groups).toHaveLength(1);
    expect(groups[0]).toMatchObject({ category: 'normal', count: 2 });
  });

  it('skips messages already shown in the Important list', () => {
    const shown = new Set([mailKey({ account: 'main', id: 'i1' })]);
    const groups = groupInbox([item('i1', 'important'), item('i2', 'important')], counts, shown);
    expect(groups[0].items.map((m) => m.id)).toEqual(['i2']);
    expect(groupInbox([item('i1', 'important')], counts, shown)).toEqual([]);
  });

  it('keeps the same id in different accounts and drops exact repeats', () => {
    const groups = groupInbox(
      [item('a', 'normal', 'main'), item('a', 'normal', 'college'), item('a', 'normal', 'main')],
      counts,
    );
    expect(groups[0].items.map(mailKey)).toEqual(['main:a', 'college:a']);
  });
});

describe('appendPage', () => {
  it('adds only messages not loaded yet, keeping order', () => {
    const merged = appendPage(
      [item('1', 'normal'), item('2', 'normal')],
      [item('2', 'normal'), item('3', 'normal')],
    );
    expect(merged.map((m) => m.id)).toEqual(['1', '2', '3']);
  });
});
