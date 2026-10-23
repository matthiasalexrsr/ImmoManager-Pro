import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import PriceIndexSection from '../features/letters/PriceIndexSection';
import { formatPriceIndex, parsePriceIndex } from '../features/letters/lettersApi';

vi.mock('../api', () => ({ api: {} }));
afterEach(() => cleanup());

describe('consumer price index for index rents', () => {
  it('reads month and value lines in the usual forms and names lines it cannot read', () => {
    expect(parsePriceIndex('2025-08;122,3\n09/2025 122,6\n10.2025\t122.9\n\n2025-13;1\nAugust 2025;122')).toEqual({
      values: { '2025-08': '122.3', '2025-09': '122.6', '2025-10': '122.9' },
      errors: ['Zeile 5: „2025-13;1“', 'Zeile 6: „August 2025;122“'],
    });
    expect(formatPriceIndex({ '2025-09': '122.6', '2025-08': '122.3' })).toBe('2025-08;122,3\n2025-09;122,6');
  });

  it('saves the series against its revision', async () => {
    const service = {
      view: vi.fn().mockResolvedValue({ revision: 2, base_year: 2020, values: { '2025-08': '122.3' }, months: ['2025-08'], can_edit: true }),
      save: vi.fn().mockResolvedValue({ revision: 3, base_year: 2020, values: { '2025-08': '122.3', '2025-09': '122.6' }, months: ['2025-08', '2025-09'], can_edit: true }),
    };
    render(<PriceIndexSection service={service} />);
    expect(await screen.findByText(/1 Monatswerte hinterlegt, zuletzt August 2025: 122,3 \(2020 = 100\)/)).toBeInTheDocument();
    const field = screen.getByLabelText('Monatswerte, je Zeile „JJJJ-MM;Wert“');
    fireEvent.change(field, { target: { value: '2025-08;122,3\nkaputt' } });
    fireEvent.click(screen.getByRole('button', { name: 'Indexwerte speichern' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Zeile 2: „kaputt“');
    expect(service.save).not.toHaveBeenCalled();
    fireEvent.change(field, { target: { value: '2025-08;122,3\n2025-09;122,6' } });
    fireEvent.click(screen.getByRole('button', { name: 'Indexwerte speichern' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('2 Monatswerte gespeichert.'));
    expect(service.save).toHaveBeenCalledWith(expect.objectContaining({ base_year: 2020, base_revision: 2,
      values: { '2025-08': '122.3', '2025-09': '122.6' } }));
  });

  it('is read-only for people who may not keep it', async () => {
    const service = { view: vi.fn().mockResolvedValue({ revision: 0, base_year: null, values: {}, months: [], can_edit: false }), save: vi.fn() };
    render(<PriceIndexSection service={service} />);
    expect(await screen.findByText('Noch keine Werte hinterlegt.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Indexwerte speichern' })).toBeNull();
  });
});
