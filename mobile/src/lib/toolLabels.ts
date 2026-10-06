// Friendly wording for the tool names the server reports (names only, never arguments).
import type { ToolStatus } from './api';

export interface ToolActivity {
  name: string;
  status: ToolStatus;
}

interface Wording {
  done: string;
  running: string;
}

const WORDING: Record<string, Wording> = {
  mail_digest: { done: 'Checked mail digest', running: 'Checking mail digest' },
  mail_search: { done: 'Searched mail', running: 'Searching mail' },
  mail_read: { done: 'Read mail', running: 'Reading mail' },
  mail_archive: { done: 'Proposed archiving mail', running: 'Preparing to archive mail' },
  mail_trash: { done: 'Proposed trashing mail', running: 'Preparing to trash mail' },
  mail_label: { done: 'Proposed relabelling mail', running: 'Preparing to relabel mail' },
  calendar_events: { done: 'Checked calendar', running: 'Checking calendar' },
  calendar_create_event: {
    done: 'Proposed a calendar event',
    running: 'Drafting a calendar event',
  },
  calendar_update_event: {
    done: 'Proposed a calendar change',
    running: 'Drafting a calendar change',
  },
  calendar_add_deadline: { done: 'Proposed a deadline', running: 'Drafting a deadline' },
  classroom_courses: { done: 'Read Classroom', running: 'Reading Classroom' },
  classroom_coursework: {
    done: 'Read Classroom coursework',
    running: 'Reading Classroom coursework',
  },
  classroom_announcements: {
    done: 'Read Classroom announcements',
    running: 'Reading Classroom announcements',
  },
  classroom_materials: { done: 'Read Classroom materials', running: 'Reading Classroom materials' },
  drive_search: { done: 'Searched Drive', running: 'Searching Drive' },
  drive_read: { done: 'Read a Drive file', running: 'Reading a Drive file' },
  mail_send: { done: 'Proposed an email', running: 'Drafting an email' },
  mail_reply: { done: 'Proposed a reply', running: 'Drafting a reply' },
  drive_upload: { done: 'Proposed a Drive upload', running: 'Preparing a Drive upload' },
  drive_share: { done: 'Proposed a Drive share', running: 'Preparing to share a Drive file' },
  drive_create_text_file: { done: 'Drafted a Drive file', running: 'Drafting a Drive file' },
  files_search: { done: 'Searched local files', running: 'Searching local files' },
  files_read: { done: 'Read a local file', running: 'Reading a local file' },
  spend_summary: { done: 'Summarised spending', running: 'Summarising spending' },
  balances: { done: 'Checked balances', running: 'Checking balances' },
  transactions: { done: 'Checked transactions', running: 'Checking transactions' },
  phone_set_alarm: { done: 'Proposed an alarm', running: 'Drafting an alarm' },
  phone_set_timer: { done: 'Proposed a timer', running: 'Drafting a timer' },
  phone_reminder: { done: 'Proposed a reminder', running: 'Drafting a reminder' },
};

function humanise(name: string): string {
  const words = name.replace(/[_-]+/g, ' ').trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : 'a tool';
}

/** "Searched mail" once finished, "Searching mail" while running. Unknown tools get a fallback. */
export function toolLabel(name: string, status: ToolStatus = 'finished'): string {
  const wording = WORDING[name];
  if (!wording) {
    if (name === 'unknown') return status === 'started' ? 'Using a tool' : 'Used a tool';
    return status === 'started' ? `Running ${humanise(name)}` : `Ran ${humanise(name)}`;
  }
  return status === 'started' ? wording.running : wording.done;
}

export interface ToolChip {
  key: string;
  label: string;
  status: ToolStatus;
  count: number;
}

/** Collapse repeated calls of the same tool in the same state into one chip with a count. */
export function summariseTools(activity: ToolActivity[]): ToolChip[] {
  const chips: ToolChip[] = [];
  for (const item of activity) {
    const key = `${item.name}:${item.status}`;
    const existing = chips.find((chip) => chip.key === key);
    if (existing) existing.count += 1;
    else
      chips.push({ key, label: toolLabel(item.name, item.status), status: item.status, count: 1 });
  }
  return chips;
}

/** One line for the collapsed header: the first label, plus how many more. */
export function toolSummaryLine(activity: ToolActivity[]): string {
  const chips = summariseTools(activity);
  if (chips.length === 0) return '';
  const running = chips.find((chip) => chip.status === 'started');
  if (running) return `${running.label}…`;
  const [first, ...rest] = chips;
  const extra = rest.reduce((sum, chip) => sum + chip.count, 0) + first.count - 1;
  return extra > 0 ? `${first.label} and ${extra} more` : first.label;
}
