import { sanitiseSenders } from '../senders';

describe('sanitiseSenders', () => {
  it('normalises prefix, suffix and case', () => {
    expect(sanitiseSenders([' ax-hdfcbk-s ', 'icicib', 'VM-SBIINB-T'])).toEqual([
      'HDFCBK',
      'ICICIB',
      'SBIINB',
    ]);
  });

  it('drops phone numbers and digit-heavy IDs', () => {
    expect(sanitiseSenders(['+919876543210', '9876543210', '123456', '1A23', '1A2'])).toEqual([]);
  });

  it('keeps names with at least two letters', () => {
    expect(sanitiseSenders(['AB1', 'A123', 'BOB'])).toEqual(['AB1', 'BOB']);
  });

  it('drops wrong lengths and bad characters', () => {
    expect(sanitiseSenders(['AB', 'ABCDEFGHIJKL', 'HDFC BK', 'HDFC_BK', 'HDFC.BK', ''])).toEqual(
      [],
    );
    expect(sanitiseSenders(['ABCDEFGHIJK'])).toEqual(['ABCDEFGHIJK']);
  });

  it('drops non-strings and non-arrays', () => {
    expect(sanitiseSenders([1, null, {}, ['HDFCBK'], 'HDFCBK'])).toEqual(['HDFCBK']);
    expect(sanitiseSenders('HDFCBK')).toEqual([]);
    expect(sanitiseSenders(undefined)).toEqual([]);
    expect(sanitiseSenders({ length: 1, 0: 'HDFCBK' })).toEqual([]);
  });

  it('de-duplicates after normalisation', () => {
    expect(sanitiseSenders(['HDFCBK', 'AX-HDFCBK-S', 'hdfcbk'])).toEqual(['HDFCBK']);
  });

  it('caps at 200 entries', () => {
    const many = Array.from({ length: 500 }, (_, i) => `AB${String(i).padStart(4, '0')}`);
    expect(sanitiseSenders(many)).toHaveLength(200);
  });
});
