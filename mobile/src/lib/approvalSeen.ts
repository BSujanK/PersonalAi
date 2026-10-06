// Which pending approvals the owner has had a chance to see in the app. The background check
// (approvalAlerts.ts) announces only what is not in this list.
import { getJson, setJson } from './prefs';

const SEEN_KEY = 'approvals.seen';

/** The ids in `pending` that have not been seen before. */
export function unseenApprovals(pending: readonly string[], seen: readonly string[]): string[] {
  const known = new Set(seen);
  return pending.filter((id) => !known.has(id));
}

/** The ids seen so far, or null before anything was recorded. */
export const loadSeenApprovals = () => getJson<string[] | null>(SEEN_KEY, null);

/** Record the pending approvals currently on screen; decided ones drop out of the list. */
export async function rememberApprovals(ids: readonly string[]): Promise<void> {
  await setJson(SEEN_KEY, [...ids]);
}
