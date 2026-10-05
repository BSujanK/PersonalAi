import { useCallback, useState } from 'react';
import { Pressable, View } from 'react-native';

import { Body, Card, Chip, ErrorText, SectionTitle } from '../../src/components/ui';
import { Screen } from '../../src/components/Screen';
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
import { errorMessage } from '../../src/lib/format';
import { usePolling } from '../../src/lib/usePolling';
import { useThemedStyles, type Palette } from '../../src/theme';

const MONEY_POLL_MS = 60_000;

const makeStyles = (_p: Palette) => ({
  chips: { flexDirection: 'row' as const, flexWrap: 'wrap' as const, gap: 8 },
  row: { flexDirection: 'row' as const, justifyContent: 'space-between' as const, gap: 8 },
  pressRow: { minHeight: 44, justifyContent: 'center' as const },
});

export default function Money() {
  const styles = useThemedStyles(makeStyles);
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

  return (
    <Screen title="Money" menu refreshing={refreshing} onRefresh={() => void refresh()}>
      <ErrorText message={error} />

      <SectionTitle>Balances</SectionTitle>
      {balances.length === 0 ? (
        <Body muted>No balances yet. Import bank SMS from Settings.</Body>
      ) : null}
      {balances.map((b) => (
        <Card key={`${b.bank}:${b.account}`}>
          <Body>
            {b.bank.toUpperCase()} {b.account}
          </Body>
          <Body>Rs {b.balance_inr}</Body>
          <Body muted>as of {b.as_of}</Body>
        </Card>
      ))}

      <SectionTitle>Spending</SectionTitle>
      <View style={styles.chips}>
        {PERIODS.map((p) => (
          <Chip
            key={p}
            label={p.replace(/_/g, ' ')}
            selected={p === period}
            onPress={() => setPeriod(p)}
          />
        ))}
      </View>
      {summary ? (
        <Card>
          <Body>Spent Rs {summary.spent_inr}</Body>
          <Body>Received Rs {summary.received_inr}</Body>
          <Body muted>
            Net Rs {summary.net_inr} - {summary.count} transactions
          </Body>
        </Card>
      ) : null}
      {summary?.by_category.map((c) => (
        <View key={c.category} style={styles.row}>
          <Body>{c.category}</Body>
          <Body>Rs {c.total_inr}</Body>
        </View>
      ))}

      <SectionTitle>Transactions</SectionTitle>
      {txns.length === 0 ? <Body muted>No transactions in this period.</Body> : null}
      {txns.map((t) => (
        <Card key={t.id}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`${t.counterparty ?? 'Unknown'}, change category`}
            style={styles.pressRow}
            onPress={() => setEditing(editing === t.id ? null : t.id)}
          >
            <View style={styles.row}>
              <Body>{t.counterparty ?? 'Unknown'}</Body>
              <Body>
                {t.direction === 'debit' ? '-' : '+'}Rs {t.amount_inr}
              </Body>
            </View>
            <Body muted>
              {t.date} - {t.category ?? 'uncategorised'}
            </Body>
          </Pressable>
          {editing === t.id ? (
            <View style={styles.chips}>
              {CATEGORIES.map((c) => (
                <Chip
                  key={c}
                  label={c}
                  selected={c === t.category}
                  onPress={() => void choose(t, c)}
                />
              ))}
            </View>
          ) : null}
        </Card>
      ))}
    </Screen>
  );
}
