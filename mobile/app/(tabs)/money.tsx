import { useCallback, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import {
  Body,
  Button,
  Card,
  colors,
  ErrorText,
  Screen,
  SectionTitle,
  Title,
} from '../../src/components/ui';
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

const MONEY_POLL_MS = 60_000;

export default function Money() {
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
    <Screen refreshing={refreshing} onRefresh={() => void refresh()}>
      <Title>Money</Title>
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
          <Pressable
            key={p}
            onPress={() => setPeriod(p)}
            style={[styles.chip, p === period && styles.chipOn]}
          >
            <Body>{p.replace(/_/g, ' ')}</Body>
          </Pressable>
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
          <Pressable onPress={() => setEditing(editing === t.id ? null : t.id)}>
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
                <Button
                  key={c}
                  label={c}
                  tone={c === t.category ? 'primary' : 'plain'}
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

const styles = StyleSheet.create({
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  chip: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 16,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  chipOn: { backgroundColor: '#dbe8ff', borderColor: colors.primary },
  row: { flexDirection: 'row', justifyContent: 'space-between', gap: 8 },
});
