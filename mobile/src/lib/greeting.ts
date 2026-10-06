/** Starter chips: a short label, and the complete request that tapping it sends. */
export const SUGGESTIONS = [
  { label: 'Emails', prompt: 'Show my latest emails, important ones first.' },
  {
    label: "Today's digest",
    prompt: "Give me today's digest: important mail, deadlines and today's events.",
  },
  { label: 'News', prompt: "What are today's top news headlines?" },
  { label: 'Account', prompt: "Show my account balances and this month's spending." },
  { label: "What's due this week?", prompt: "What's due this week?" },
] as const;

/** "Good morning" before noon, "Good afternoon" until 5pm, otherwise "Good evening". */
export function greeting(now: Date = new Date()): string {
  const hour = now.getHours();
  if (hour >= 5 && hour < 12) return 'Good morning';
  if (hour >= 12 && hour < 17) return 'Good afternoon';
  return 'Good evening';
}
