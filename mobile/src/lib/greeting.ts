export const SUGGESTIONS = [
  "What's due this week?",
  "Today's digest",
  'How much did I spend this month?',
  'Any important mail?',
] as const;

/** "Good morning" before noon, "Good afternoon" until 5pm, otherwise "Good evening". */
export function greeting(now: Date = new Date()): string {
  const hour = now.getHours();
  if (hour >= 5 && hour < 12) return 'Good morning';
  if (hour >= 12 && hour < 17) return 'Good afternoon';
  return 'Good evening';
}
