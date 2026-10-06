import { labelFor } from '../accountLabels';

jest.mock('../api', () => ({ getAccounts: jest.fn() }));

describe('labelFor', () => {
  it('uses the configured label, case-insensitively, else the address itself', () => {
    const labels = { 'college@example.edu': 'College' };
    expect(labelFor(labels, 'College@Example.edu')).toBe('College');
    expect(labelFor(labels, 'me@example.com')).toBe('me@example.com');
  });
});
