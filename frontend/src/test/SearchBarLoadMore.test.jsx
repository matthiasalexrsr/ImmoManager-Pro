import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import SearchBar from '../components/SearchBar';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn() } }));
vi.mock('../i18n', () => ({
  useTranslation: () => ({
    t: (key, vars) => ({
      'search.global.loadMore': 'Weitere laden',
      'search.global.shownOf': `${vars?.shown} von ${vars?.total}`,
    })[key] || key,
  }),
}));

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
