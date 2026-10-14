import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import SearchBar from '../components/SearchBar';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn() } }));
const auth = vi.hoisted(() => ({ user: null }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => auth }));
vi.mock('../i18n', () => ({
  useTranslation: () => ({
    t: (key, vars) => ({
      'search.global.loadMore': 'Weitere laden',
      'search.global.shownOf': `${vars?.shown} von ${vars?.total}`,
    })[key] || key,
  }),
}));

function Where() { return <span data-testid="where">{useLocation().pathname}</span>; }

const hit = (id) => ({ entity_type: 'tenant', id, display: `Mieter ${id}`, detail: '', url: '/tenants' });

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe('SearchBar', () => {
  it('shows the total of a group and appends its next page', async () => {
    api.get
      .mockResolvedValueOnce({
        results: [hit('a'), hit('b')],
        groups: [{ entity_type: 'tenant', total: 3, has_more: true, next_cursor: 'c1' }],
      })
      .mockResolvedValueOnce({
        results: [hit('c')],
        groups: [{ entity_type: 'tenant', total: 3, has_more: false, next_cursor: null }],
      });
    render(<MemoryRouter><SearchBar /></MemoryRouter>);
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'Mieter' } });

    expect(await screen.findByText('Mieter b', {}, { timeout: 2000 })).toBeTruthy();
    expect(screen.getByText(/2 von 3/)).toBeTruthy();
    fireEvent.click(screen.getByText('Weitere laden'));

    expect(await screen.findByText('Mieter c')).toBeTruthy();
    expect(api.get).toHaveBeenLastCalledWith('/search?q=Mieter&type=tenant&limit=25&cursor=c1');
    await waitFor(() => expect(screen.queryByText('Weitere laden')).toBeNull());
    expect(screen.queryByText(/von 3/)).toBeNull();
  });
});

describe('SearchBar pages and recently opened records', () => {
  afterEach(() => { localStorage.clear(); auth.user = null; });

  it('offers matching pages by name, also typed without umlauts, and opens the first with Enter', async () => {
    api.get.mockResolvedValue({ results: [], groups: [] });
    render(<MemoryRouter initialEntries={['/']}><SearchBar /><Routes><Route path="*" element={<Where />} /></Routes></MemoryRouter>);
    const box = screen.getByRole('searchbox');
    fireEvent.focus(box);
    fireEvent.change(box, { target: { value: 'uebergabe' } });
    expect(screen.getByText('Seiten')).toBeTruthy();
    expect(screen.getByRole('option', { name: /Übergabeprotokolle/ })).toBeTruthy();
    await waitFor(() => expect(api.get).toHaveBeenCalled(), { timeout: 2000 });
    // a found page is a result: no "nothing found" below it
    await waitFor(() => expect(screen.queryByText('ui.table.loading')).toBeNull());
    expect(screen.queryByText('search.global.noResults')).toBeNull();
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(screen.getByTestId('where')).toHaveTextContent('/handover-protocols');
  });

  it('does not open a record of an earlier query with Enter while the new one is loading', async () => {
    api.get.mockResolvedValueOnce({ results: [hit('a')], groups: [{ entity_type: 'tenant', total: 1 }] });
    render(<MemoryRouter initialEntries={['/']}><SearchBar /><Routes><Route path="*" element={<Where />} /></Routes></MemoryRouter>);
    const box = screen.getByRole('searchbox');
    fireEvent.change(box, { target: { value: 'Anna' } });
    expect(await screen.findByText('Mieter a', {}, { timeout: 2000 })).toBeTruthy();
    fireEvent.change(box, { target: { value: 'Annabel' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(screen.getByTestId('where')).toHaveTextContent(/^\/$/);
  });

  it('lists the records opened from the search for an empty query until cleared', async () => {
    api.get.mockResolvedValueOnce({ results: [hit('a')], groups: [{ entity_type: 'tenant', total: 1 }] });
    auth.user = { id: 'u1' };
    render(<MemoryRouter><SearchBar /></MemoryRouter>);
    const box = screen.getByRole('searchbox');
    fireEvent.change(box, { target: { value: 'Mieter' } });
    fireEvent.click(await screen.findByText('Mieter a', {}, { timeout: 2000 }));
    expect(JSON.parse(localStorage.getItem('recent_search:u1'))).toEqual([
      { entity_type: 'tenant', id: 'a', display: 'Mieter a', detail: '', url: '/tenants' }]);

    fireEvent.focus(box);
    expect(screen.getByText('Zuletzt geöffnet')).toBeTruthy();
    expect(screen.getByRole('option', { name: /Mieter a/ })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Verlauf leeren' }));
    expect(screen.queryByText('Zuletzt geöffnet')).toBeNull();
    expect(localStorage.getItem('recent_search:u1')).toBe('[]');
  });
});
