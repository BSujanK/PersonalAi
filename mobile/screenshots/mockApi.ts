/* eslint-disable import/export -- intentional: these stand-ins shadow the real exports. */
// Screenshot harness only (see metro.config.js): the agent API answered from synthetic data.
// Every name, address, account and amount here is made up (example.com, fake account numbers).
import vectors from '../../shared/test-vectors/action-previews.json';
import type {
  AccountInfo,
  AlertFeed,
  AlertSettings,
  Approval,
  Balance,
  ChatReply,
  ChatStreamHandlers,
  ConversationDetail,
  ConversationPage,
  DecisionResult,
  FileSearch,
  InboxPage,
  MailMessage,
  Period,
  SpendSummary,
  Today,
  Txn,
  UpcomingDeadline,
} from '../src/lib/api';

// Re-export the real module, then shadow the functions the screens call: an explicit export
// takes precedence over `export *`, which is exactly the point here.
export * from '../src/lib/api';

const ago = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();
const ahead = (minutes: number) => new Date(Date.now() + minutes * 60_000).toISOString();
const later = (hours: number) => {
  const d = new Date();
  d.setHours(hours, 0, 0, 0);
  return d.toISOString();
};
const resolve = <T>(value: T) => new Promise<T>((r) => setTimeout(() => r(value), 30));
const params = () =>
  typeof location === 'undefined' ? new URLSearchParams() : new URLSearchParams(location.search);

// Two made-up Google accounts: a personal one shown in full, a college one with a label.
const PERSONAL = 'me@example.com';
const COLLEGE = 'student@college.example.com';

export const health = () => resolve({ status: 'ok' });
export const getAccounts = (): Promise<{ accounts: AccountInfo[] }> =>
  resolve({
    accounts: [
      { account: PERSONAL, label: PERSONAL, kinds: ['mail', 'calendar', 'drive'] },
      { account: COLLEGE, label: 'College', kinds: ['mail', 'calendar', 'classroom', 'drive'] },
    ],
  });

// --- Home ---------------------------------------------------------------------------------------

export const getToday = (): Promise<Today> =>
  resolve({
    generated_at: ago(1),
    mail: {
      important: [
        {
          account: COLLEGE,
          id: 'm1',
          from_name: 'Prof. Anita Rao',
          from_addr: 'anita.rao@college.example.com',
          subject: 'Lab report 4: submission moved to Friday',
          snippet: 'The deadline for lab report 4 is now Friday at 5 pm.',
          reason: 'Deadline',
          received: ago(35),
        },
        {
          account: PERSONAL,
          id: 'm2',
          from_name: 'Placement Cell',
          from_addr: 'placements@college.example.com',
          subject: 'Interview slot confirmed: Tuesday 11:00',
          snippet: 'Your interview with Example Labs is confirmed.',
          reason: 'Interview',
          received: ago(160),
        },
      ],
      counts: { important: 2, normal: 14, promo: 9 },
      unclassified: 0,
    },
    events: [
      { id: 'e1', summary: 'Data Structures lecture', start: later(14), location: 'Room 204' },
      { id: 'e2', summary: 'Project sync with Ravi', start: later(17), location: 'Library' },
    ],
    deadlines: [],
  });

export const getDeadlines = (): Promise<{ items: UpcomingDeadline[] }> =>
  resolve({
    items: [
      {
        id: 1,
        kind: 'assignment',
        title: 'Lab report 4',
        due: ahead(60 * 50),
        source: 'classroom',
        source_account: COLLEGE,
        source_id: 'c1',
        calendar_added: true,
        status: 'active',
      },
      {
        id: 2,
        kind: 'fee',
        title: 'Semester fee payment',
        due: ahead(60 * 24 * 5),
        source: 'mail',
        source_account: PERSONAL,
        source_id: 'm9',
        calendar_added: false,
        status: 'active',
      },
    ],
  });

export const getInbox = (): Promise<InboxPage> =>
  resolve({
    items: [
      [
        'm3',
        'Ravi Kumar',
        'ravi@example.com',
        'Notes from today’s project sync',
        'normal',
        50,
        true,
      ],
      [
        'm4',
        'Example Bank',
        'alerts@bank.example.com',
        'Your statement is ready',
        'normal',
        240,
        false,
      ],
      ['m5', 'Meera Iyer', 'meera@example.com', 'Weekend trip plan', 'normal', 900, false],
      [
        'm6',
        'ShopKart',
        'offers@shop.example.com',
        'Festive sale: up to 60% off',
        'promo',
        1500,
        true,
      ],
    ].map(([id, name, addr, subject, category, minutes, unread]) => ({
      account: PERSONAL,
      id: id as string,
      message_id: `<${id as string}@example.com>`,
      thread_id: `t-${id as string}`,
      category: category as 'normal' | 'promo',
      from_name: name as string,
      from_addr: addr as string,
      subject: subject as string,
      snippet: '',
      reason: null,
      received: ago(minutes as number),
      unread: unread as boolean,
    })),
    counts: { important: 2, normal: 14, promo: 9, spam: 0, unclassified: 0 },
    next_cursor: null,
  });

// --- Money --------------------------------------------------------------------------------------

const SUMMARIES: Partial<Record<Period, SpendSummary>> = {
  today: summary('1240', '0', 3, []),
  yesterday: summary('1560', '0', 4, []),
};

function summary(
  spent: string,
  received: string,
  count: number,
  byCategory: SpendSummary['by_category'],
): SpendSummary {
  const net = String(Number(received) - Number(spent));
  return {
    from: ago(60 * 24 * 30),
    to: ago(0),
    count,
    spent_inr: spent,
    received_inr: received,
    net_inr: net,
    by_category: byCategory,
    top_counterparties: [],
  };
}

export const getSummary = (period: Period): Promise<SpendSummary> =>
  resolve(
    SUMMARIES[period] ??
      summary('18450', '42000', 38, [
        { category: 'food', total_inr: '6120', count: 14 },
        { category: 'travel', total_inr: '4300', count: 6 },
        { category: 'shopping', total_inr: '3890', count: 5 },
        { category: 'bills', total_inr: '2640', count: 3 },
        { category: 'subscriptions', total_inr: '1500', count: 4 },
      ]),
  );

export const getBalances = (): Promise<{ accounts: Balance[] }> =>
  resolve({
    accounts: [
      { bank: 'bob', account: 'XX4821', balance_inr: '86240.50', as_of: ago(40), source: 'sms' },
      { bank: 'hdfc', account: 'XX0937', balance_inr: '38110.00', as_of: ago(600), source: 'sms' },
    ],
  });

export const getTransactions = (): Promise<{ transactions: Txn[] }> =>
  resolve({
    transactions: [
      txn(1, 'credit', '42000', 'Example Labs (stipend)', 'income'),
      txn(2, 'debit', '420', 'Campus Cafe', 'food'),
      txn(3, 'debit', '1299', 'MetroRail card', 'travel'),
      txn(4, 'debit', '649', 'StreamBox', 'subscriptions'),
      txn(5, 'debit', '2340', 'FreshMart', 'groceries'),
      txn(6, 'debit', '180', 'Auto ride', null),
    ],
  });

function txn(
  id: number,
  direction: 'debit' | 'credit',
  amount: string,
  counterparty: string,
  category: string | null,
): Txn {
  const d = new Date(Date.now() - id * 26 * 3_600_000);
  return {
    id,
    date: d.toISOString().slice(0, 10),
    direction,
    amount_inr: amount,
    counterparty,
    account: 'XX4821',
    category,
    sources: ['sms'],
  };
}

export const setCategory = () => resolve({});

// --- Approvals ----------------------------------------------------------------------------------

const APPROVALS: Approval[] = [
  {
    id: 'a1',
    tool_name: vectors.mail_send.tool,
    preview: vectors.mail_send.preview,
    payload_hash: 'synthetic',
    nonce: 'synthetic',
    status: 'pending',
    created_at: ago(2),
    expires_at: ahead(13),
  },
  {
    id: 'a2',
    tool_name: vectors.share_anyone.tool,
    preview: vectors.share_anyone.preview,
    payload_hash: 'synthetic',
    nonce: 'synthetic',
    status: 'pending',
    created_at: ago(4),
    expires_at: ahead(2),
  },
];

export const listApprovals = (): Promise<Approval[]> =>
  resolve(params().has('noapprovals') ? [] : APPROVALS);
export const getApproval = (id: string): Promise<Approval> =>
  resolve(APPROVALS.find((a) => a.id === id) ?? APPROVALS[0]);
export const decideApproval = (id: string): Promise<DecisionResult> =>
  resolve({ id, status: 'rejected' });

// --- Chat ---------------------------------------------------------------------------------------

export const listConversations = (): Promise<ConversationPage> =>
  resolve({
    items: [
      {
        id: 'c1',
        title: 'What’s due this week?',
        updated_at: ago(20),
        preview: 'Lab report 4 is due Friday…',
      },
      {
        id: 'c2',
        title: 'Spending in September',
        updated_at: ago(60 * 26),
        preview: 'You spent ₹18,450…',
      },
      {
        id: 'c3',
        title: 'Reply to Ravi about the sync',
        updated_at: ago(60 * 50),
        preview: 'Draft ready for approval',
      },
      {
        id: 'c4',
        title: 'Top news headlines',
        updated_at: ago(60 * 75),
        preview: 'Three stories this morning',
      },
    ],
    next_cursor: null,
  });

export const getConversation = (id: string): Promise<ConversationDetail> =>
  resolve({
    id,
    title: 'What’s due this week?',
    updated_at: ago(20),
    messages: [
      {
        id: 'u1',
        role: 'user',
        text: 'What’s due this week? And email Ravi the lab notes.',
        created_at: ago(21),
        tools: [],
        pending_action_ids: [],
      },
      {
        id: 'r1',
        role: 'assistant',
        text: 'Two things are due this week:\n\n- **Lab report 4**: Friday, 5 pm (already on your calendar)\n- **Semester fee**: Tuesday\n\nI drafted the email to Ravi with the notes attached. It needs your approval before it is sent.',
        created_at: ago(20),
        tools: [
          { name: 'deadlines', status: 'finished' },
          { name: 'mail_search', status: 'finished' },
        ],
        pending_action_ids: ['a1'],
      },
    ],
  });

export const renameConversation = (id: string, title: string) =>
  resolve({ id, title, updated_at: ago(0), preview: '' });
export const deleteConversation = () => resolve({});

/** Streams a tool step and then waits, so the thinking spark can be captured. */
export function chatStream(
  _message: string,
  _conversationId: string | null,
  handlers: ChatStreamHandlers,
): Promise<ChatReply> {
  handlers.onStart?.('c9');
  setTimeout(() => handlers.onTool?.('mail_search', 'started'), 100);
  return new Promise(() => undefined);
}

// --- Mail, files, alerts ------------------------------------------------------------------------

export const getMailMessage = (account: string, id: string): Promise<MailMessage> =>
  resolve({
    account,
    id,
    thread_id: 't-m1',
    from: { name: 'Prof. Anita Rao', addr: 'anita.rao@college.example.com' },
    to: [{ name: 'You', addr: 'student@college.example.com' }],
    cc: [{ name: 'Lab TAs', addr: 'lab-tas@college.example.com' }],
    date: ago(35),
    subject: 'Lab report 4: submission moved to Friday',
    labels: ['INBOX', 'College'],
    category: 'important',
    reason: 'Deadline',
    body: 'Hello all,\n\nThe deadline for lab report 4 has moved to Friday at 5 pm. Please submit it on Classroom as a single PDF, and include your raw readings as an appendix.\n\nThe rubric is attached. Office hours are on Thursday from 3 to 4 pm.\n\nRegards,\nAnita Rao',
    body_truncated: false,
    attachments: [{ name: 'lab4-rubric.pdf', mime: 'application/pdf', size: 182_400 }],
    source: 'live',
  } as MailMessage);

export const searchFiles = (): Promise<FileSearch> =>
  resolve({
    local: [
      {
        source: 'local',
        path: 'Documents/College/lab4-readings.xlsx',
        name: 'lab4-readings.xlsx',
        size: 48_200,
        modified: ago(60 * 20),
      },
      {
        source: 'local',
        path: 'Documents/College/lab4-draft.docx',
        name: 'lab4-draft.docx',
        size: 221_000,
        modified: ago(90),
      },
    ],
    drive: [
      {
        source: 'drive',
        account: COLLEGE,
        id: 'd1',
        name: 'Lab 4 shared notes',
        mime: 'application/vnd.google-apps.document',
        size: null,
        modified: ago(300),
      },
    ],
    errors: [],
  });

export const getNotifications = (): Promise<AlertFeed> =>
  resolve({
    items: [
      {
        id: 4,
        kind: 'calendar_added',
        title: 'Added to your calendar: Lab report 4',
        body: 'Due Friday at 5 pm. From Google Classroom.',
        created_at: ago(30),
        target: {
          type: 'deadline',
          deadline_id: 1,
          source: 'classroom',
          account: COLLEGE,
          course_id: 'c1',
        },
        actions: ['undo'],
        source_account: COLLEGE,
        source_label: 'College',
      },
      {
        id: 3,
        kind: 'important_mail',
        title: 'Prof. Anita Rao',
        body: 'Lab report 4: submission moved to Friday',
        created_at: ago(35),
        target: { type: 'mail', account: COLLEGE, id: 'm1', message_id: 'm1' },
        source_account: COLLEGE,
        source_label: 'College',
      },
      {
        id: 2,
        kind: 'deadline',
        title: 'Semester fee due Tuesday',
        body: 'Found in mail from Accounts Office.',
        created_at: ago(300),
        target: {
          type: 'deadline',
          deadline_id: 2,
          source: 'mail',
          account: PERSONAL,
          message_id: 'm9',
        },
        source_account: PERSONAL,
        source_label: PERSONAL,
      },
      {
        id: 1,
        kind: 'briefing',
        title: 'Morning briefing',
        body: '2 important mails, 2 events and 2 deadlines today.',
        created_at: ago(600),
        target: { type: 'today' },
      },
    ],
    latest_id: 4,
  });

let alertSettings: AlertSettings = {
  important_mail: true,
  deadlines: true,
  briefing: true,
  briefing_time: '07:30',
};
export const getAlertSettings = () => resolve(alertSettings);
export const putAlertSettings = (next: AlertSettings) => {
  alertSettings = next;
  return resolve(next);
};
export const undoAutoEvent = () => resolve({ status: 'undone' });

export const getSmsSenders = () => resolve({ senders: ['BOBTXN', 'BOBSMS', 'HDFCBK'] });
export const postSms = () => resolve({ accepted: 0 });
export const getDeviceCommands = () => resolve({ commands: [] });
export const ackDeviceCommand = () => resolve({});
export const putPushToken = () => resolve({});
export const deletePushToken = () => resolve({});
