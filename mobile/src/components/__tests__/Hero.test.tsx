import { render, screen } from '@testing-library/react-native';

import { darkPalette } from '../../theme';
import { Hero, inrWhole } from '../Hero';

describe('inrWhole', () => {
  it('groups whole rupees the Indian way', () => {
    expect(inrWhole(0)).toBe('₹0');
    expect(inrWhole(999)).toBe('₹999');
    expect(inrWhole(1240)).toBe('₹1,240');
    expect(inrWhole(1234567)).toBe('₹12,34,567');
    expect(inrWhole(-50000.4)).toBe('−₹50,000');
  });
});

describe('Hero', () => {
  it('reads the exact figure and the delta as one element', async () => {
    await render(
      <Hero
        label="Spent today"
        amount={1240}
        delta={{ text: '₹320 less than yesterday', direction: 'down', good: true }}
        palette={darkPalette}
      />,
    );
    expect(screen.getByLabelText('Spent today: ₹1,240. ₹320 less than yesterday')).toBeTruthy();
    expect(screen.getByText('₹320 less than yesterday')).toBeTruthy();
  });
});
