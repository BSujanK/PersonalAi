// The agent's summary of a mail. It arrives from the server as untrusted wire data, so every part
// is validated here before it reaches the UI: strings only, trimmed, clipped, and capped in count.
import type { MailSummary, MailSummaryAction, MailSummaryResponse } from './api';

export const MAX_SUMMARY_TEXT = 2000;
export const MAX_POINTS = 12;
export const MAX_POINT_LENGTH = 400;
export const MAX_ACTIONS = 10;
export const MAX_ACTION_LENGTH = 300;
export const MAX_DUE_LENGTH = 64;
const MAX_MODEL_LENGTH = 100;

function clip(value: string, max: number): string {
  return value.length <= max ? value : `${value.slice(0, max - 1).trimEnd()}…`;
}

/** A trimmed, clipped, non-empty string; null for anything else. */
function cleanText(value: unknown, max: number): string | null {
  if (typeof value !== 'string') return null;
  const text = value.trim();
  return text ? clip(text, max) : null;
}

function parseAction(entry: unknown): MailSummaryAction | null {
  if (typeof entry !== 'object' || entry === null) return null;
  const { text, due } = entry as { text?: unknown; due?: unknown };
  const clean = cleanText(text, MAX_ACTION_LENGTH);
  return clean ? { text: clean, due: cleanText(due, MAX_DUE_LENGTH) } : null;
}

/** Whether a summary has anything to show: a lone empty section is not worth a card. */
export function hasSummaryContent(summary: MailSummary): boolean {
  return summary.text !== '' || summary.points.length > 0 || summary.actions.length > 0;
}

/**
 * Narrow an untrusted `/mail/.../summary` body. Items of the wrong type are dropped, long ones
 * clipped; null when there is no summary object or nothing in it survives.
 */
export function parseMailSummary(raw: unknown): MailSummaryResponse | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const { summary: untrusted, cached, model } = raw as Record<string, unknown>;
  if (typeof untrusted !== 'object' || untrusted === null) return null;
  const { text, points, actions } = untrusted as Record<string, unknown>;
  const summary: MailSummary = {
    text: cleanText(text, MAX_SUMMARY_TEXT) ?? '',
    points: (Array.isArray(points) ? points : [])
      .map((point) => cleanText(point, MAX_POINT_LENGTH))
      .filter((point): point is string => point !== null)
      .slice(0, MAX_POINTS),
    actions: (Array.isArray(actions) ? actions : [])
      .map(parseAction)
      .filter((action): action is MailSummaryAction => action !== null)
      .slice(0, MAX_ACTIONS),
  };
  if (!hasSummaryContent(summary)) return null;
  return {
    summary,
    cached: cached === true,
    model: cleanText(model, MAX_MODEL_LENGTH) ?? '',
  };
}

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

/**
 * An action's due date as a short local date ("Fri 17 Oct"). An all-day date is read as that
 * calendar day, whatever the time zone. Text that is not a date is shown as written.
 */
export function summaryDueLabel(due: string | null | undefined): string | null {
  const text = due?.trim();
  if (!text) return null;
  const match = DATE_ONLY.exec(text);
  const date = match
    ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
    : new Date(text);
  if (Number.isNaN(date.getTime())) return text;
  return date
    .toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })
    .replace(',', '');
}
