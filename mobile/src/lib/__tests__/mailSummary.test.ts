import {
  hasSummaryContent,
  MAX_ACTIONS,
  MAX_ACTION_LENGTH,
  MAX_POINTS,
  MAX_POINT_LENGTH,
  MAX_SUMMARY_TEXT,
  parseMailSummary,
  summaryDueLabel,
} from '../mailSummary';

const body = (summary: unknown, extra: Record<string, unknown> = {}) => ({
  summary,
  cached: false,
  model: 'm',
  ...extra,
});

describe('parseMailSummary', () => {
  it('keeps a well-formed summary', () => {
    const parsed = parseMailSummary(
      body(
        {
          text: ' Build failed on main. ',
          points: ['Test suite red', 'Last green: Monday'],
          actions: [
            { text: 'Fix the test', due: '2026-10-17' },
            { text: 'Tell Ravi', due: null },
          ],
        },
        { cached: true, model: 'some-model' },
      ),
    );
    expect(parsed).toEqual({
      summary: {
        text: 'Build failed on main.',
        points: ['Test suite red', 'Last green: Monday'],
        actions: [
          { text: 'Fix the test', due: '2026-10-17' },
          { text: 'Tell Ravi', due: null },
        ],
      },
      cached: true,
      model: 'some-model',
    });
  });

  it('rejects payloads that are not a summary object', () => {
    for (const raw of [null, undefined, 'x', 3, [], {}, { summary: null }, { summary: 'text' }]) {
      expect(parseMailSummary(raw)).toBeNull();
    }
  });

  it('treats a summary with nothing in it as no summary', () => {
    expect(parseMailSummary(body({ text: '  ', points: [], actions: [] }))).toBeNull();
    expect(
      parseMailSummary(body({ text: 4, points: [1, null, ''], actions: ['x', {}] })),
    ).toBeNull();
  });

  it('drops items of the wrong type and blank ones', () => {
    const parsed = parseMailSummary(
      body({
        text: 7,
        points: ['ok', 3, null, '  ', { a: 1 }, 'also ok'],
        actions: [
          { text: 'real', due: 5 },
          { text: 9, due: '2026-10-17' },
          null,
          'string',
          { text: '   ', due: null },
        ],
      }),
    );
    expect(parsed?.summary).toEqual({
      text: '',
      points: ['ok', 'also ok'],
      actions: [{ text: 'real', due: null }],
    });
  });

  it('tolerates missing or non-array lists', () => {
    const parsed = parseMailSummary(body({ text: 'Just text', points: 'nope' }));
    expect(parsed?.summary).toEqual({ text: 'Just text', points: [], actions: [] });
  });

  it('clips absurd lengths and counts', () => {
    const parsed = parseMailSummary(
      body({
        text: 'a'.repeat(MAX_SUMMARY_TEXT * 3),
        points: Array.from({ length: 50 }, () => 'p'.repeat(MAX_POINT_LENGTH * 2)),
        actions: Array.from({ length: 50 }, () => ({
          text: 't'.repeat(MAX_ACTION_LENGTH * 2),
          due: 'd'.repeat(500),
        })),
      }),
    );
    const summary = parsed!.summary;
    expect(summary.text).toHaveLength(MAX_SUMMARY_TEXT);
    expect(summary.text.endsWith('…')).toBe(true);
    expect(summary.points).toHaveLength(MAX_POINTS);
    expect(summary.points.every((p) => p.length <= MAX_POINT_LENGTH)).toBe(true);
    expect(summary.actions).toHaveLength(MAX_ACTIONS);
    expect(summary.actions.every((a) => a.text.length <= MAX_ACTION_LENGTH)).toBe(true);
    expect(summary.actions.every((a) => a.due !== null && a.due.length <= 64)).toBe(true);
  });

  it('defaults the metadata when it is missing or the wrong type', () => {
    const parsed = parseMailSummary({ summary: { text: 'x' }, cached: 'yes', model: 4 });
    expect(parsed).toMatchObject({ cached: false, model: '' });
  });
});

describe('hasSummaryContent', () => {
  it('is true when any one section has something', () => {
    expect(hasSummaryContent({ text: '', points: [], actions: [] })).toBe(false);
    expect(hasSummaryContent({ text: 'x', points: [], actions: [] })).toBe(true);
    expect(hasSummaryContent({ text: '', points: ['x'], actions: [] })).toBe(true);
    expect(hasSummaryContent({ text: '', points: [], actions: [{ text: 'x', due: null }] })).toBe(
      true,
    );
  });
});

describe('summaryDueLabel', () => {
  it('shows an all-day date as that calendar day, weekday first', () => {
    const label = summaryDueLabel('2026-10-17');
    expect(label).toMatch(/Sat/);
    expect(label).toMatch(/17/);
    expect(label).toMatch(/Oct/);
    expect(label).not.toContain(',');
  });

  it('shows a datetime as a date without the time', () => {
    const label = summaryDueLabel('2026-10-17T12:00:00Z');
    expect(label).toMatch(/Oct/);
    expect(label).not.toMatch(/:/);
  });

  it('is null for no due date', () => {
    for (const due of [null, undefined, '', '   ']) expect(summaryDueLabel(due)).toBeNull();
  });

  it('shows text that is not a date as written', () => {
    expect(summaryDueLabel(' end of month ')).toBe('end of month');
  });
});
