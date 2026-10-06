import { useCallback, useState } from 'react';
import { ScrollView, Text, View } from 'react-native';

import { Screen } from '../../src/components/Screen';
import { Chip, EmptyRow, ErrorText, ListRow, ListSection } from '../../src/components/ui';
import {
  CATEGORIES,
  PERIODS,
  getBalances,
  getSummary,
  getTransactions,
  setCategory,
  type Balance,
  type Period,
  type SpendSummary,
  type Txn,
} from '../../src/lib/api';
import { errorMessage, formatInr, periodLabel, shortDateTime } from '../../src/lib/format';
import { usePolling } from '../../src/lib/usePolling';
import {
  fontFamily,
  radius,
  ROW_INSET,
  space,
  type,
  useTheme,
  useThemedStyles,
  type Palette,
} from '../../src/theme';

const MONEY_POLL_MS = 60_000;

const makeStyles = (p: Palette) => ({
  periods: { gap: space.sm, paddingHorizontal: space.md },
  periodsBleed: { marginHorizontal: -space.md },
  hero: { backgroundColor: p.surface, borderRadius: radius.lg, padding: space.md, gap: space.md },
  heroLabel: { ...type.footnote, fontFamily: fontFamily.bodySemiBold, color: p.textMuted },
  heroValue: { ...type.largeTitle, color: p.text, fontVariant: ['tabular-nums' as const] },
  heroRow: { flexDirection: 'row' as const, gap: space.md },
  heroCell: { flex: 1, gap: 2 },
  heroSmall: { ...type.headline, color: p.text, fontVariant: ['tabular-nums' as const] },
  heroCaption: { ...type.footnote, color: p.textMuted },
  amount: { ...type.body, fontVariant: ['tabular-nums' as const] },
  barTrack: {
    height: 4,
    borderRadius: 2,
    backgroundColor: p.muted,
    marginTop: space.xs,
    overflow: 'hidden' as const,
  },
  barFill: { position: 'absolute' as const, left: 0, top: 0, bottom: 0, borderRadius: 2 },
  catChips: {
    flexDirection: 'row' as const,
    flexWrap: 'wrap' as const,
    gap: space.sm,
    paddingHorizontal: ROW_INSET,
    paddingBottom: space.md - space.xs,
    backgroundColor: p.surface,
  },
});

/** A static proportion bar (absolute and childless, so it never re-lays-out its siblings). */
function Bar({ share }: { share: number }) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  const pct = Math.max(2, Math.min(100, Math.round(share * 100)));
  return (
    <View style={styles.barTrack}>
      <View style={[styles.barFill, { width: `${pct}%`, backgroundColor: palette.accent }]} />
    </View>
  );
}

export default function Money() {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  const [period, setPeriod] = useState<Period>('this_month');
  const [balances, setBalances] = useState<Balance[]>([]);
  const [summary, setSummary] = useState<SpendSummary | null>(null);
  const [txns, setTxns] = useState<Txn[]>([]);
  const [editing, setEditing] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [b, s, t] = await Promise.all([
        getBalances(),
        getSummary(period),
        getTransactions(period),
      ]);
      setBalances(b.accounts);
      setSummary(s);
      setTxns(t.transactions);
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [period]);

  usePolling(load, MONEY_POLL_MS);

  async function refresh() {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }

  async function choose(txn: Txn, category: (typeof CATEGORIES)[number]) {
    try {
      await setCategory(txn.id, category);
      setEditing(null);
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  const spent = summary ? Number(summary.spent_inr) || 0 : 0;

  return (
    <Screen
      title="Money"
      subtitle={periodLabel(period)}
      menu
      refreshing={refreshing}
      onRefresh={() => void refresh()}
    >
      <ErrorText message={error} />

      <ListSection
        title="Balances"
        inset="icon"
        footer="From the latest bank SMS. Balances are never estimated."
      >
        {balances.length === 0 ? (
          <EmptyRow>No balances yet. Import bank SMS from Settings.</EmptyRow>
        ) : null}
        {balances.map((b) => (
          <ListRow
            key={`${b.bank}:${b.account}`}
            icon="credit-card"
            title={`${b.bank.toUpperCase()} ${b.account}`}
            subtitle={`as of ${shortDateTime(b.as_of)}`}
            value={formatInr(b.balance_inr)}
            accessibilityLabel={`${b.bank} account ${b.account}, balance ${formatInr(b.balance_inr)}`}
          />
        ))}
      </ListSection>

      <View style={styles.periodsBleed}>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.periods}
          accessibilityLabel="Period"
        >
          {PERIODS.map((p) => (
            <Chip
              key={p}
              label={periodLabel(p)}
              selected={p === period}
              onPress={() => setPeriod(p)}
            />
          ))}
        </ScrollView>
      </View>

      {summary ? (
        <View
          style={styles.hero}
          accessible
          accessibilityLabel={`Spent ${formatInr(summary.spent_inr)}, received ${formatInr(summary.received_inr)}, net ${formatInr(summary.net_inr)}, ${summary.count} transactions`}
        >
          <View>
            <Text style={styles.heroLabel}>SPENT</Text>
            <Text style={styles.heroValue} adjustsFontSizeToFit numberOfLines={1}>
              {formatInr(summary.spent_inr)}
            </Text>
          </View>
          <View style={styles.heroRow}>
            <View style={styles.heroCell}>
              <Text style={styles.heroCaption}>Received</Text>
              <Text style={[styles.heroSmall, { color: palette.accentText }]}>
                {formatInr(summary.received_inr)}
              </Text>
            </View>
            <View style={styles.heroCell}>
              <Text style={styles.heroCaption}>Net</Text>
              <Text style={styles.heroSmall}>{formatInr(summary.net_inr)}</Text>
            </View>
            <View style={styles.heroCell}>
              <Text style={styles.heroCaption}>Transactions</Text>
              <Text style={styles.heroSmall}>{summary.count}</Text>
            </View>
          </View>
        </View>
      ) : null}

      {summary && summary.by_category.length > 0 ? (
        <ListSection title="By category">
          {summary.by_category.map((c) => (
            <ListRow
              key={c.category}
              title={periodLabel(c.category)}
              subtitle={`${c.count} transaction${c.count === 1 ? '' : 's'}`}
              value={formatInr(c.total_inr)}
            >
              <Bar share={spent > 0 ? (Number(c.total_inr) || 0) / spent : 0} />
            </ListRow>
          ))}
        </ListSection>
      ) : null}

      <ListSection title="Transactions" footer="Tap a transaction to change its category.">
        {txns.length === 0 ? <EmptyRow>No transactions in this period.</EmptyRow> : null}
        {txns.map((t) => {
          const open = editing === t.id;
          const credit = t.direction === 'credit';
          return (
            <View key={t.id}>
              <ListRow
                title={t.counterparty ?? 'Unknown'}
                subtitle={`${t.date} · ${t.category ?? 'uncategorised'}`}
                accessibilityLabel={`${t.counterparty ?? 'Unknown'}, ${credit ? 'received' : 'spent'} ${formatInr(t.amount_inr)}, ${t.category ?? 'uncategorised'}`}
                accessibilityHint={open ? 'Hides categories' : 'Shows categories to choose from'}
                selected={open}
                onPress={() => setEditing(open ? null : t.id)}
                accessory={
                  <Text
                    style={[styles.amount, { color: credit ? palette.accentText : palette.text }]}
                  >
                    {credit ? '+' : '−'}
                    {formatInr(t.amount_inr)}
                  </Text>
                }
              />
              {open ? (
                <View style={styles.catChips}>
                  {CATEGORIES.map((c) => (
                    <Chip
                      key={c}
                      label={periodLabel(c)}
                      selected={c === t.category}
                      onPress={() => void choose(t, c)}
                    />
                  ))}
                </View>
              ) : null}
            </View>
          );
        })}
      </ListSection>
    </Screen>
  );
}
