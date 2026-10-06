import { appendText, applyToolEvent, beginTurn, finishTurn } from '../chatState';
import { THINKING_STATUS, thinkingStatus, toolStatus } from '../toolLabels';

describe('tool status verbs', () => {
  it.each([
    ['web_search', 'Searching the web…'],
    ['web_read', 'Reading pages…'],
    ['hf_models', 'Looking at Hugging Face…'],
    ['mail_digest', 'Checking your mail…'],
    ['mail_search', 'Checking your mail…'],
    ['mail_read', 'Checking your mail…'],
    ['drive_search', 'Looking through Drive…'],
    ['drive_read', 'Looking through Drive…'],
    ['files_search', 'Searching your files…'],
    ['files_read', 'Searching your files…'],
    ['spend_summary', 'Summarising spending…'],
    ['calendar_events', 'Checking the calendar…'],
    ['news_headlines', 'Reading the news…'],
    ['mail_send', 'Preparing an action…'],
    ['drive_share', 'Preparing an action…'],
    ['calendar_create_event', 'Preparing an action…'],
    ['phone_reminder', 'Preparing an action…'],
    ['mail_trash', 'Preparing an action…'],
  ])('%s -> %s', (name, phrase) => {
    expect(toolStatus(name)).toBe(phrase);
  });

  it('calls an unknown tool "Working…" and never echoes its name', () => {
    expect(toolStatus('something_new')).toBe('Working…');
    expect(toolStatus('unknown')).toBe('Working…');
    expect(toolStatus('something_new')).not.toMatch(/something/);
  });
});

describe('thinking status sequence', () => {
  const turn = () => beginTurn([], 'u1', 'a1', 'Any news on the new model?');
  const status = (messages: ReturnType<typeof turn>) => thinkingStatus(messages[1].tools);

  it('starts as Thinking, follows each started tool, and stays on it until the next', () => {
    let m = turn();
    expect(status(m)).toBe(THINKING_STATUS);
    m = applyToolEvent(m, 'a1', 'web_search', 'started');
    expect(status(m)).toBe('Searching the web…');
    m = applyToolEvent(m, 'a1', 'web_search', 'finished');
    expect(status(m)).toBe('Searching the web…');
    m = applyToolEvent(m, 'a1', 'web_read', 'started');
    expect(status(m)).toBe('Reading pages…');
    m = applyToolEvent(m, 'a1', 'web_read', 'finished');
    m = applyToolEvent(m, 'a1', 'mystery', 'started');
    expect(status(m)).toBe('Working…');
  });

  it('is only ever a verb phrase: nothing from the question is carried into it', () => {
    const m = applyToolEvent(turn(), 'a1', 'mail_search', 'started');
    expect(JSON.stringify(m[1].tools)).not.toMatch(/news|model/i);
    expect(status(m)).toBe('Checking your mail…');
  });

  it('first answer text ends the status phase; done settles the turn', () => {
    let m = applyToolEvent(turn(), 'a1', 'web_search', 'started');
    expect(m[1]).toMatchObject({ state: 'streaming', text: '' });
    m = appendText(m, 'a1', 'Here is');
    expect(m[1].text).not.toBe('');
    m = finishTurn(m, 'a1', 'Here is what I found.', []);
    expect(m[1].state).toBe('done');
    expect(m[1].tools).toEqual([{ name: 'web_search', status: 'finished' }]);
  });
});
