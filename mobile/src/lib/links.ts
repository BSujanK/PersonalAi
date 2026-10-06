// The only links the app opens in the browser on the agent's say-so. Anything else is not opened.
// Exactly an event link (`/calendar/event?eid=<base64url>`): no other path, no other parameter,
// so nothing can ride along to Google's redirector or another page.
const CALENDAR_EVENT =
  /^https:\/\/(www\.google\.com|calendar\.google\.com)\/calendar\/event\?eid=[A-Za-z0-9_-]+$/;

/** A link to an event in Google Calendar, and nothing else. */
export function isGoogleCalendarLink(link: string): boolean {
  return CALENDAR_EVENT.test(link);
}
