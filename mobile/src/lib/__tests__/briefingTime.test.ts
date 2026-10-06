import { isValidBriefingTime } from '../briefingTime';

describe('isValidBriefingTime', () => {
  it.each(['00:00', '07:30', '12:05', '19:59', '23:59'])('accepts %s', (value) => {
    expect(isValidBriefingTime(value)).toBe(true);
  });

  it.each([
    '',
    '7:30',
    '24:00',
    '12:60',
    '07:3',
    '07-30',
    '0730',
    ' 07:30',
    '07:30 ',
    '07:30:00',
    'ab:cd',
  ])('rejects %p', (value) => {
    expect(isValidBriefingTime(value)).toBe(false);
  });
});
