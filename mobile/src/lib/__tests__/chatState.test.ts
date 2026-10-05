import {
  appendText,
  applyToolEvent,
  beginTurn,
  failTurn,
  finishTurn,
  fromDisplay,
  promptFor,
  resetText,
  stopTurn,
} from '../chatState';
import { greeting, SUGGESTIONS } from '../greeting';
import { summariseTools, toolLabel, toolSummaryLine } from '../toolLabels';
import { outcomeOf } from '../approvalFlow';

jest.mock('../secureKeys', () => ({ signWithBiometrics: jest.fn() }));
jest.mock('../deviceCommands', () => ({ processDeviceCommands: jest.fn() }));

const turn = () => beginTurn([], 'u1', 'a1', 'What is due?');

describe('chat transcript state', () => {
  it('starts a turn with the question and an empty streaming answer', () => {
    const messages = turn();
    expect(messages.map((m) => [m.role, m.state, m.text])).toEqual([
      ['user', 'done', 'What is due?'],
      ['assistant', 'streaming', ''],
    ]);
  });

  it('streams text, resets it, and finishes with the final reply and action ids', () => {
    let m = appendText(turn(), 'a1', 'Let me ');
    m = appendText(m, 'a1', 'check.');
    expect(m[1].text).toBe('Let me check.');
    m = resetText(m, 'a1');
    expect(m[1].text).toBe('');
    m = finishTurn(m, 'a1', 'Two things.', ['x1']);
    expect(m[1]).toMatchObject({ text: 'Two things.', actionIds: ['x1'], state: 'done' });
  });

  it('tracks a tool from started to finished and closes any left running', () => {
    let m = applyToolEvent(turn(), 'a1', 'mail_search', 'started');
    m = applyToolEvent(m, 'a1', 'mail_search', 'finished');
    m = applyToolEvent(m, 'a1', 'balances', 'started');
    expect(m[1].tools).toEqual([
      { name: 'mail_search', status: 'finished' },
      { name: 'balances', status: 'started' },
    ]);
    expect(finishTurn(m, 'a1', 'ok', [])[1].tools[1].status).toBe('finished');
    expect(failTurn(m, 'a1', 'boom')[1]).toMatchObject({ state: 'error', error: 'boom' });
    expect(failTurn(m, 'a1', 'boom')[1].tools[1].status).toBe('failed');
    expect(stopTurn(m, 'a1')[1].state).toBe('stopped');
  });

  it('records an ending event that had no start', () => {
    const m = applyToolEvent(turn(), 'a1', 'balances', 'finished');
    expect(m[1].tools).toEqual([{ name: 'balances', status: 'finished' }]);
  });

  it('maps stored messages and finds the prompt to retry', () => {
    const user = fromDisplay({
      id: 'u',
      role: 'user',
      text: 'hi',
      created_at: 'x',
      tools: [],
      pending_action_ids: [],
    });
    const assistant = fromDisplay({
      id: 'a',
      role: 'assistant',
      text: 'hello',
      created_at: 'x',
      tools: [{ name: 'mail_read', status: 'finished' }],
      pending_action_ids: ['p1'],
    });
    expect(assistant).toMatchObject({ state: 'done', actionIds: ['p1'] });
    expect(promptFor([user, assistant], 'a')).toBe('hi');
    expect(promptFor([assistant], 'a')).toBeNull();
  });
});

describe('tool labels', () => {
  it('uses friendly wording', () => {
    expect(toolLabel('mail_search')).toBe('Searched mail');
    expect(toolLabel('mail_search', 'started')).toBe('Searching mail');
    expect(toolLabel('classroom_courses')).toBe('Read Classroom');
    expect(toolLabel('balances')).toBe('Checked balances');
    expect(toolLabel('unknown')).toBe('Used a tool');
    expect(toolLabel('some_new_tool')).toBe('Ran Some new tool');
  });

  it('merges repeats and summarises', () => {
    const activity = [
      { name: 'mail_search', status: 'finished' as const },
      { name: 'mail_search', status: 'finished' as const },
      { name: 'balances', status: 'finished' as const },
    ];
    expect(summariseTools(activity)).toHaveLength(2);
    expect(summariseTools(activity)[0]).toMatchObject({ label: 'Searched mail', count: 2 });
    expect(toolSummaryLine(activity)).toBe('Searched mail and 2 more');
    expect(toolSummaryLine([activity[2]])).toBe('Checked balances');
    expect(toolSummaryLine([{ name: 'drive_search', status: 'started' }])).toBe('Searching Drive…');
    expect(toolSummaryLine([])).toBe('');
  });
});

describe('greeting', () => {
  const at = (h: number) => new Date(2026, 9, 6, h, 0);
  it('follows the time of day', () => {
    expect(greeting(at(7))).toBe('Good morning');
    expect(greeting(at(13))).toBe('Good afternoon');
    expect(greeting(at(19))).toBe('Good evening');
    expect(greeting(at(2))).toBe('Good evening');
  });
  it('offers the four starter questions', () => {
    expect(SUGGESTIONS).toHaveLength(4);
  });
});

describe('approval outcome', () => {
  const later = new Date(Date.now() + 60_000).toISOString();
  const earlier = new Date(Date.now() - 60_000).toISOString();
  it('collapses server statuses', () => {
    expect(outcomeOf('pending', later)).toBe('pending');
    expect(outcomeOf('pending', earlier)).toBe('expired');
    expect(outcomeOf('executed', earlier)).toBe('approved');
    expect(outcomeOf('approved', later)).toBe('approved');
    expect(outcomeOf('rejected', later)).toBe('rejected');
    expect(outcomeOf('failed', later)).toBe('failed');
    expect(outcomeOf('expired', later)).toBe('expired');
  });
});
