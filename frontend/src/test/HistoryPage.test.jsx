import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { api } from '../api';
import History from '../pages/History';

vi.mock('../api', () => ({ api: { get: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => ({
  'status.badge.vacant': 'Leer', 'status.badge.occupied': 'Vermietet', 'navigation.secondary.history': 'Änderungshistorie',
}[key] || key) }) }));

const entry = (id, extra) => ({ id, entity_type: 'unit', entity_id: 'u1', changed_by: 'user-1',
  changed_at: '2026-10-18T21:51:00', reason: 'Feld geändert', entity_title: 'WE 3', entity_href: '/units/u1',
  changed_by_name: 'Linda Reiser', ...extra });

beforeEach(() => vi.resetAllMocks());
afterEach(cleanup);

it('names the record, the field and both values in words and opens the record', async () => {
  api.get.mockResolvedValueOnce({ items: [
    entry('a', { field_name: 'status', old_value: 'vacant', new_value: 'occupied' }),
    entry('b', { field_name: 'cold_rent', old_value: '480.0', new_value: '500' }),
    entry('c', { entity_type: 'contact', entity_id: 'c-gone-1234', field_name: 'notes', old_value: null, new_value: 'Dach',
      entity_title: null, entity_href: null, changed_by_name: null, changed_by: null }),
  ], next_cursor: null });
  await act(async () => { render(<MemoryRouter><History /></MemoryRouter>); });

  expect(screen.getAllByText('Status').length).toBeGreaterThan(0);
  expect(screen.getByText('Leer')).toBeInTheDocument();
  expect(screen.getByText('Vermietet')).toBeInTheDocument();
  expect(screen.getByText('Kaltmiete')).toBeInTheDocument();
  expect(screen.getByText(/480,00\s€/)).toBeInTheDocument();
  expect(screen.getByText(/500,00\s€/)).toBeInTheDocument();
  expect(screen.getAllByRole('link', { name: 'WE 3' })[0]).toHaveAttribute('href', '/units/u1');
  expect(screen.getAllByText('Linda Reiser').length).toBeGreaterThan(0);
  // a deleted record and a change without an account stay readable
  expect(screen.getByText('c-gone-1234 (nicht verfügbar)')).toBeInTheDocument();
  expect(screen.getByText('System')).toBeInTheDocument();
  expect(screen.getByText('Nicht angegeben')).toBeInTheDocument();
  expect(screen.queryByText('in_progress')).toBeNull();
  expect(screen.getByRole('button', { name: 'Ältere Änderungen' })).toBeDisabled();
});

it('loads older changes after a full page', async () => {
  const full = Array.from({ length: 100 }, (_, index) => entry(`n${index}`, { field_name: 'notes', new_value: `Neu ${index}` }));
  api.get.mockResolvedValueOnce({ items: full, next_cursor: 'older' }).mockResolvedValueOnce({ items: [entry('old', { field_name: 'notes', new_value: 'Ganz alt' })], next_cursor: null });
  await act(async () => { render(<MemoryRouter><History /></MemoryRouter>); });
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Ältere Änderungen' })); });
  expect(api.get).toHaveBeenLastCalledWith('/history/page?limit=100&cursor=older', expect.objectContaining({ signal: expect.any(AbortSignal) }));
  expect(screen.getByText('Ganz alt')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Ältere Änderungen' })).toBeDisabled();
});
