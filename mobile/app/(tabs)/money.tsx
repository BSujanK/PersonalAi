import { useCallback, useEffect, useRef, useState } from 'react';
import { ScrollView, Text, View } from 'react-native';
import Animated, {
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withDelay,
  withTiming,
} from 'react-native-reanimated';

import type { IconName } from '../../src/components/Icon';
import { Hero, type Delta } from '../../src/components/Hero';
import { Screen } from '../../src/components/Screen';
import {
  Card,
  Chip,
  EmptyRow,
  ErrorText,
  ListRow,
  ListSection,
  Stagger,
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
import { errorMessage, formatInr, periodLabel, shortDateTime } from '../../src/lib/format';
import { usePolling } from '../../src/lib/usePolling';
import {
  fontFamily,
  motion,
  radius,
  space,
  timingEaseOut,
  type,
  useTheme,
  useThemedStyles,
  type Palette,
} from '../../src/theme';

const MONEY_POLL_MS = 60_000;

const CATEGORY_ICONS: Record<string, IconName> = {
  food: 'coffee',
  groceries: 'shopping-bag',
  shopping: 'shopping-cart',
  travel: 'map',
  fuel: 'droplet',
  bills: 'file-text',
  rent: 'home',
  education: 'book-open',
  health: 'heart',
  entertainment: 'film',
  subscriptions: 'repeat',
  cash: 'dollar-sign',
  transfer: 'repeat',
  income: 'arrow-down-left',
  fees: 'percent',
  investment: 'trending-up',
  other: 'tag',
};

const makeStyles = (p: Palette) => ({
  periods: { gap: space.sm, paddingHorizontal: space.md },
  periodsBleed: { marginHorizontal: -space.md },
  stats: { flexDirection: 'row' as const, gap: space.sm + space.xs },
  stat: {
    flex: 1,
    gap: space.xs,
    padding: space.md - space.xs,
    borderRadius: radius.card,
    backgroundColor: p.surface,
    borderWidth: 1,
    borderColor: p.glassBorder,
  },
  statLabel: { ...type.caption, color: p.textMuted },
  statValue: {
    ...type.headline,
    fontSize: 16,
    color: p.text,
    fontVariant: ['tabular-nums' as const],
  },
  catRow: { gap: space.sm },
  catHead: { flexDirection: 'row' as const, alignItems: 'center' as const, gap: space.sm },
  catName: { ...type.subhead, fontFamily: fontFamily.bodyMedium, color: p.text, flex: 1 },
  catAmount: {
    ...type.subhead,
    fontFamily: fontFamily.bodySemiBold,
    color: p.text,
    fontVariant: ['tabular-nums' as const],
  },
  catCount: { ...type.caption, color: p.textMuted },
  barTrack: {
    height: 8,
    borderRadius: 4,
    backgroundColor: p.muted,
    overflow: 'hidden' as const,
  },
  barFill: {
    position: 'absolute' as const,
    left: 0,
    top: 0,
    bottom: 0,
    borderRadius: 4,
    backgroundColor: p.accent,
  },
  catChips: {
    flexDirection: 'row' as const,
    flexWrap: 'wrap' as const,
    gap: space.sm,
    paddingTop: space.sm,
  },
});

/**
 * A spend bar that grows from its leading edge once, on first show. The fill is absolute and
 * childless, so its scale never re-lays-out anything else.
 */
function Bar({ share, index }: { share: number; index: number }) {
  const styles = useThemedStyles(makeStyles);
  const reduced = useReducedMotion();
  const pct = Math.max(2, Math.min(100, Math.round(share * 100)));
  const grow = useSharedValue(reduced ? 1 : 0);
  useEffect(() => {
    if (reduced) return;
    grow.set(
      withDelay(
        Math.min(index, motion.staggerMax) * motion.staggerMs,
        withTiming(1, { duration: motion.countUpMs, easing: timingEaseOut }),
      ),
    );
  }, [grow, index, reduced]);
  const fillStyle = useAnimatedStyle(() => ({ transform: [{ scaleX: grow.get() }] }));
  return (
    <View style={styles.barTrack}>
      <Animated.View
        style={[styles.barFill, { width: `${pct}%`, transformOrigin: 'left center' }, fillStyle]}
      />
    </View>
  );
}

export default function Money() {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  const [period, setPeriod] = useState<Period>('this_month');
  const pills = useRef<ScrollView>(null);
  const pillsPlaced = useRef(false);
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
  const net = summary ? Number(summary.net_inr) || 0 : 0;
  const total = balances.reduce((sum, b) => sum + (Number(b.balance_inr) || 0), 0);
  const delta: Delta | null = summary
    ? {
        text: `${net >= 0 ? '+' : '−'}${formatInr(String(Math.round(Math.abs(net))))} net · ${periodLabel(period).toLowerCase()}`,
        direction: net === 0 ? 'flat' : net > 0 ? 'up' : 'down',
        good: net > 0,
      }
    : null;

  return (
    <Screen tabs title="Money" refreshing={refreshing} onRefresh={() => void refresh()}>
      <ErrorText message={error} />

      <Hero
        label={balances.length > 0 ? 'Total balance' : 'Spent'}
        amount={Math.round(balances.length > 0 ? total : spent)}
        delta={delta}
        palette={palette}
      />

      <View style={styles.periodsBleed}>
        <ScrollView
          ref={pills}
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.periods}
          accessibilityLabel="Period"
        >
          {PERIODS.map((p) => (
            <View
              key={p}
              onLayout={(e) => {
                // Bring the starting period into view once; later choices are where the finger is.
                if (p !== period || pillsPlaced.current) return;
                pillsPlaced.current = true;
                pills.current?.scrollTo({ x: e.nativeEvent.layout.x - space.md, animated: false });
              }}
            >
              <Chip label={periodLabel(p)} selected={p === period} onPress={() => setPeriod(p)} />
            </View>
          ))}
        </ScrollView>
      </View>

      {summary ? (
        <View
          style={styles.stats}
          accessible
          accessibilityLabel={`Spent ${formatInr(summary.spent_inr)}, received ${formatInr(summary.received_inr)}, ${summary.count} transactions`}
        >
          <View style={styles.stat}>
            <Text style={styles.statLabel}>Spent</Text>
            <Text
              style={[styles.statValue, { color: palette.danger }]}
              numberOfLines={1}
              adjustsFontSizeToFit
            >
              {formatInr(String(Math.round(spent)))}
            </Text>
          </View>
          <View style={styles.stat}>
            <Text style={styles.statLabel}>Received</Text>
            <Text
              style={[styles.statValue, { color: palette.ok }]}
              numberOfLines={1}
              adjustsFontSizeToFit
            >
              {formatInr(String(Math.round(Number(summary.received_inr) || 0)))}
            </Text>
          </View>
          <View style={styles.stat}>
            <Text style={styles.statLabel}>Transactions</Text>
            <Text style={styles.statValue}>{summary.count}</Text>
          </View>
        </View>
      ) : null}

      {summary && summary.by_category.length > 0 ? (
        <ListSection title="Spend by category">
          <Card style={{ gap: space.md }}>
            {summary.by_category.map((c, i) => (
              <View
                key={c.category}
                style={styles.catRow}
                accessible
                accessibilityLabel={`${periodLabel(c.category)}: ${formatInr(c.total_inr)}, ${c.count} transaction${c.count === 1 ? '' : 's'}`}
              >
                <View style={styles.catHead}>
                  <Text style={styles.catName} numberOfLines={1}>
                    {periodLabel(c.category)}
                  </Text>
                  <Text style={styles.catCount}>{c.count}×</Text>
                  <Text style={styles.catAmount}>{formatInr(c.total_inr)}</Text>
                </View>
                <Bar share={spent > 0 ? (Number(c.total_inr) || 0) / spent : 0} index={i} />
              </View>
            ))}
          </Card>
        </ListSection>
      ) : null}

      <ListSection
        title="Accounts"
        footer="From the latest bank SMS. Balances are never estimated."
      >
        {balances.length === 0 ? (
          <EmptyRow>No balances yet. Import bank SMS from Settings.</EmptyRow>
        ) : null}
        {balances.map((b, i) => (
          <Stagger key={`${b.bank}:${b.account}`} index={i}>
            <ListRow
              icon="credit-card"
              title={`${b.bank.toUpperCase()} ${b.account}`}
              subtitle={`as of ${shortDateTime(b.as_of)}`}
              value={formatInr(b.balance_inr)}
              accessibilityLabel={`${b.bank} account ${b.account}, balance ${formatInr(b.balance_inr)}`}
            />
          </Stagger>
        ))}
      </ListSection>

      <ListSection title="Transactions" footer="Tap a transaction to change its category." stagger>
        {txns.length === 0 ? <EmptyRow>No transactions in this period.</EmptyRow> : null}
        {txns.map((t) => {
          const open = editing === t.id;
          const credit = t.direction === 'credit';
          return (
            <ListRow
              key={t.id}
              icon={CATEGORY_ICONS[t.category ?? 'other'] ?? 'tag'}
              iconTint={credit ? palette.ok : palette.accentText}
              title={t.counterparty ?? 'Unknown'}
              subtitle={`${t.date} · ${t.category ? periodLabel(t.category) : 'Uncategorised'}`}
              subtitleLines={1}
              value={`${credit ? '+' : '−'}${formatInr(t.amount_inr)}`}
              dot={credit ? palette.ok : palette.danger}
              accessibilityLabel={`${t.counterparty ?? 'Unknown'}, ${credit ? 'received' : 'spent'} ${formatInr(t.amount_inr)}, ${t.category ?? 'uncategorised'}`}
              accessibilityHint={open ? 'Hides categories' : 'Shows categories to choose from'}
              selected={open}
              onPress={() => setEditing(open ? null : t.id)}
            >
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
            </ListRow>
          );
        })}
      </ListSection>
    </Screen>
  );
}
