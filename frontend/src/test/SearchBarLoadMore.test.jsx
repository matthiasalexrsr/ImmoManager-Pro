import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
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
function WhereWithSearch() { const location = useLocation(); return <span data-testid="where">{location.pathname + location.search}</span>; }

const hit = (id) => ({ entity_type: 'tenant', id, display: `Mieter ${id}`, detail: '', url: '/tenants' });
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe('SearchBar', () => {
  it('keeps the latest query when an older request finishes later', async () => {
    const old = deferred();
    api.get.mockReturnValueOnce(old.promise).mockResolvedValueOnce({ results: [hit('new')], groups: [] });
    render(<MemoryRouter><SearchBar /></MemoryRouter>);
    const box = screen.getByRole('searchbox');
    fireEvent.change(box, { target: { value: 'Anna' } });
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1));
    fireEvent.change(box, { target: { value: 'Ben' } });
    expect(await screen.findByText('Mieter new')).toBeInTheDocument();
    await act(async () => old.resolve({ results: [hit('old')], groups: [] }));
    expect(screen.getByText('Mieter new')).toBeInTheDocument();
    expect(screen.queryByText('Mieter old')).not.toBeInTheDocument();
    expect(screen.queryByText('ui.table.loading')).not.toBeInTheDocument();
  });

  it('discards a load-more response from an earlier query', async () => {
    const more = deferred();
    api.get.mockResolvedValueOnce({ results: [hit('first')], groups: [{ entity_type: 'tenant', total: 2, next_cursor: 'old' }] })
      .mockReturnValueOnce(more.promise).mockResolvedValueOnce({ results: [hit('new')], groups: [] });
    render(<MemoryRouter><SearchBar /></MemoryRouter>);
    const box = screen.getByRole('searchbox');
    fireEvent.change(box, { target: { value: 'Anna' } });
    fireEvent.click(await screen.findByText('Weitere laden'));
    fireEvent.change(box, { target: { value: 'Ben' } });
    expect(await screen.findByText('Mieter new')).toBeInTheDocument();
    await act(async () => more.resolve({ results: [hit('stale')], groups: [{ entity_type: 'tenant', next_cursor: 'stale' }] }));
    expect(screen.queryByText('Mieter stale')).not.toBeInTheDocument();
    expect(screen.queryByText('Weitere laden')).not.toBeInTheDocument();
  });

  it('uses the visible group order for keyboard selection', async () => {
    api.get.mockResolvedValueOnce({ results: [hit('first'), { entity_type: 'property', id: 'p1', display: 'Haus', url: '/properties/p1' }, hit('last')], groups: [] });
    render(<MemoryRouter><SearchBar /><Where /></MemoryRouter>);
    const box = screen.getByRole('searchbox');
    fireEvent.change(box, { target: { value: 'xyz' } });
    await screen.findByText('Mieter last');
    screen.getAllByRole('option').forEach(option => { option.scrollIntoView = vi.fn(); });
    fireEvent.keyDown(box, { key: 'ArrowDown' });
    fireEvent.keyDown(box, { key: 'ArrowDown' });
    expect(screen.getByRole('option', { name: /Mieter last/ })).toHaveAttribute('aria-selected', 'true');
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(screen.getByTestId('where')).toHaveTextContent('/tenants');
  });

  it('leaves focus inside a modal when Ctrl+K is pressed', () => {
    render(<MemoryRouter><SearchBar /><div role="dialog" aria-modal="true"><input aria-label="Draft" /></div></MemoryRouter>);
    const draft = screen.getByLabelText('Draft');
    draft.focus();
    fireEvent.keyDown(draft, { key: 'k', ctrlKey: true });
    expect(draft).toHaveFocus();
  });
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

  it('ignores malformed recent records and nonlocal destinations', () => {
    auth.user = { id: 'u1' };
    localStorage.setItem('recent_search:u1', JSON.stringify([
      { ...hit('object'), display: { bad: true } },
      { ...hit('detail'), detail: { bad: true } },
      { ...hit('external'), url: '//example.org' },
      { ...hit('slash'), url: '/\\example.org' },
      hit('valid'),
    ]));
    render(<MemoryRouter><SearchBar /></MemoryRouter>);
    fireEvent.focus(screen.getByRole('searchbox'));
    expect(screen.getAllByRole('option')).toHaveLength(1);
    expect(screen.getByRole('option', { name: /Mieter valid/ })).toBeInTheDocument();
  });

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

describe('SearchBar quick actions', () => {
  afterEach(() => { auth.user = null; auth.write = undefined; });

  it('offers "Neue Buchung" for "buchung" and opens the page with its New form request', () => {
    api.get.mockResolvedValue({ results: [], groups: [] });
    render(<MemoryRouter initialEntries={['/']}><SearchBar /><Routes><Route path="*" element={<WhereWithSearch />} /></Routes></MemoryRouter>);
    const box = screen.getByRole('searchbox');
    fireEvent.change(box, { target: { value: 'buchung' } });
    expect(screen.getByText('Aktionen')).toBeTruthy();
    expect(screen.getByRole('option', { name: /Neue Buchung/ })).toBeTruthy();
    // Enter at once, while the records are still loading
    fireEvent.change(box, { target: { value: 'neue buchung' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(screen.getByTestId('where')).toHaveTextContent('/bookings?neu=1');
  });

  it('offers no actions to a role that may not change the area', () => {
    api.get.mockResolvedValue({ results: [], groups: [] });
    auth.user = { id: 'r1', role: 'readonly' };
    auth.write = [];
    render(<MemoryRouter><SearchBar /></MemoryRouter>);
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'buchung' } });
    expect(screen.getByRole('option', { name: /Buchungen/ })).toBeTruthy();
    expect(screen.queryByText('Aktionen')).toBeNull();
    expect(screen.queryByRole('option', { name: /Neue Buchung/ })).toBeNull();
  });
});


it('behält nach dem Löschen der Suchanfrage den Fokus im Suchfeld', () => {
  render(<MemoryRouter><SearchBar /></MemoryRouter>);
  const box = screen.getByRole('searchbox');
  fireEvent.change(box, { target: { value: 'Miete' } });
  const clear = screen.getByRole('button', { name: 'Suche löschen' });
  clear.focus();
  fireEvent.click(clear);
  expect(box).toHaveValue('');
  expect(box).toHaveFocus();
  expect(screen.queryByRole('button', { name: 'Suche löschen' })).not.toBeInTheDocument();
});

it('shows amounts and codes of a hit in words and opens the found record', async () => {
  auth.user = null;
  api.get.mockResolvedValue({ results: [
    { entity_type: 'invoice', id: 'i1', display: 'Dachdeckerei Kunze', detail: '1249.18', url: '/invoices?focus_id=i1' },
    { entity_type: 'category', id: 'c1', display: 'Wartung', detail: 'expense', url: '/categories?focus_id=c1' },
  ], groups: [] });
  render(<MemoryRouter initialEntries={['/']}><SearchBar /><Routes><Route path="*" element={<WhereWithSearch />} /></Routes></MemoryRouter>);
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'Kunze' } });
  const invoice = await screen.findByRole('option', { name: /Dachdeckerei Kunze/ });
  expect(invoice.textContent.replace(/\s/g, ' ')).toContain('1.249,18 €');
  expect(screen.getByRole('option', { name: /Wartung/ })).toHaveTextContent('Ausgabe');
  expect(screen.queryByText('1249.18')).toBeNull();
  fireEvent.click(invoice);
  expect(screen.getByTestId('where')).toHaveTextContent('/invoices?focus_id=i1');
});
