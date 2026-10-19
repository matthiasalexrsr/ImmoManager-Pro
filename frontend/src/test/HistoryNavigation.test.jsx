import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider, useNavigate } from 'react-router-dom';
import History from '../pages/History';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => ({ 'navigation.secondary.history': 'Änderungshistorie', 'ui.table.loading': 'Laden …' }[key] || key) }) }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => false, useAuth: () => null }));

const row = (id, fields = {}) => ({ id, entity_type: 'contract', entity_id: `contract-${id}`, field_name: `Feld ${id}`,
  old_value: 'Vorher', new_value: 'Nachher', changed_at: '2000-01-01T12:00:00Z', changed_by: 'user-id', ...fields });
const query = url => new URL(url, 'https://test.invalid').searchParams;
const table = () => screen.getByRole('table', { name: 'Änderungshistorie' });

function Page() {
  const navigate = useNavigate();
  return <><button onClick={() => navigate(-1)}>Browser zurück</button><History /></>;
}

function mount(initial = '/history') {
  const router = createMemoryRouter([{ path: '/history', element: <Page /> }], { initialEntries: [initial] });
  return render(<RouterProvider router={router} />);
}

beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); sessionStorage.clear(); });
afterEach(cleanup);

describe('complete, navigable history pages', () => {
  it('shows every row in a server page, follows old cursors and supports Back and reset without a global cutoff', async () => {
    const first = Array.from({ length: 100 }, (_, index) => row(String(index)));
    api.get.mockImplementation(async url => query(url).get('cursor')
      ? { items: [row('older-than-500')], next_cursor: null }
      : { items: first, next_cursor: 'opaque-older-page' });
    mount();
    await screen.findByText('Feld 99');
    expect(within(table()).getAllByRole('row')).toHaveLength(101);
    expect(screen.getByRole('button', { name: 'CSV – aktuelle Seite' })).toBeInTheDocument();
    expect(screen.getByText(/CSV-Export enthält ausschließlich diese Seite/)).toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: /durchsuchen/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Ältere Änderungen' }));
    await screen.findByText('Feld older-than-500');
    expect(screen.queryByText('Feld 99')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ältere Änderungen' })).toBeDisabled();
    expect(query(api.get.mock.calls.at(-1)[0]).get('cursor')).toBe('opaque-older-page');
    fireEvent.click(screen.getByRole('button', { name: 'Browser zurück' }));
    await screen.findByText('Feld 99');
    fireEvent.click(screen.getByRole('button', { name: 'Ältere Änderungen' }));
    await screen.findByText('Feld older-than-500');
    fireEvent.click(screen.getByRole('button', { name: 'Neueste Änderungen' }));
    await screen.findByText('Feld 99');
    expect(query(api.get.mock.calls.at(-1)[0]).has('cursor')).toBe(false);
    expect(api.get.mock.calls.every(([url]) => url.startsWith('/history/page?') && query(url).get('limit') === '100')).toBe(true);
  });

  it('filters on the server and clears the previous cursor when choosing another entity', async () => {
    api.get.mockImplementation(async url => ({ items: [row(query(url).get('entity_type') ? 'filtered' : 'unfiltered')], next_cursor: null }));
    mount('/history?cursor=old-cursor');
    await screen.findByText('Feld unfiltered');
    fireEvent.change(screen.getByRole('textbox', { name: 'Entität' }), { target: { value: 'contract' } });
    fireEvent.change(screen.getByRole('textbox', { name: 'Datensatz-ID' }), { target: { value: 'contract /?#' } });
    fireEvent.click(screen.getByRole('button', { name: 'Historie filtern' }));
    await screen.findByText('Feld filtered');
    const request = query(api.get.mock.calls.at(-1)[0]);
    expect(request.get('entity_type')).toBe('contract');
    expect(request.get('entity_id')).toBe('contract /?#');
    expect(request.has('cursor')).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Filter zurücksetzen' }));
    await screen.findByText('Feld unfiltered');
    expect(screen.getByRole('textbox', { name: 'Datensatz-ID' })).toHaveValue('');
  });

  it('retries a failed older page without displaying the previous page or a false empty history', async () => {
    api.get.mockResolvedValueOnce({ items: [row('newest')], next_cursor: 'older' })
      .mockRejectedValueOnce(new Error('Verlaufsspeicher nicht erreichbar'))
      .mockResolvedValueOnce({ items: [row('recovered')], next_cursor: null });
    mount();
    await screen.findByText('Feld newest');
    fireEvent.click(screen.getByRole('button', { name: 'Ältere Änderungen' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Verlaufsspeicher nicht erreichbar');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.queryByText('Feld newest')).not.toBeInTheDocument();
    expect(screen.queryByText(/Keine weiteren älteren Änderungen/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
    await screen.findByText('Feld recovered');
    expect(query(api.get.mock.calls[1][0]).get('cursor')).toBe('older');
    expect(query(api.get.mock.calls[2][0]).get('cursor')).toBe('older');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('expands full historical values and links a full record ID to its exact source', async () => {
    const fullOld = 'Historischer Vertragswert '.repeat(12) + 'ALTER SCHLUSSWERT';
    const fullNew = 'Berichtigter Vertragswert '.repeat(12) + 'NEUER SCHLUSSWERT';
    const identifier = 'contract/with a full ?# identifier';
    api.get.mockResolvedValue({ items: [row('detail', { entity_id: identifier, old_value: fullOld, new_value: fullNew }),
      row('unknown', { entity_type: 'unknown-legacy-kind', entity_id: 'full-legacy-record-identifier' })], next_cursor: null });
    mount();
    const link = await screen.findByRole('link', { name: identifier });
    expect(link).toHaveAttribute('href', `/contracts?contract_id=${encodeURIComponent(identifier)}`);
    const cells = within(link.closest('tr')).getAllByRole('cell');
    const oldValue = within(cells[5]).getByText(fullOld);
    const newValue = within(cells[6]).getByText(fullNew);
    expect(oldValue).not.toBeVisible();
    expect(newValue).not.toBeVisible();
    fireEvent.click(within(cells[5]).getByText(/Vollständiger Wert/));
    fireEvent.click(within(cells[6]).getByText(/Vollständiger Wert/));
    expect(oldValue).toBeVisible();
    expect(newValue).toBeVisible();
    expect(screen.getByText('full-legacy-record-identifier')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'full-legacy-record-identifier' })).not.toBeInTheDocument();
  });

  it('discards a late response after filters change and rejects a malformed page instead of showing empty results', async () => {
    let resolveOld;
    api.get.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }))
      .mockResolvedValueOnce({ items: [row('current-filter')], next_cursor: null })
      .mockResolvedValueOnce({ wrong: 'not a history page' });
    mount();
    await waitFor(() => expect(api.get).toHaveBeenCalledOnce());
    const originalSignal = api.get.mock.calls[0][1].signal;
    fireEvent.change(screen.getByRole('textbox', { name: 'Entität' }), { target: { value: 'contract' } });
    fireEvent.click(screen.getByRole('button', { name: 'Historie filtern' }));
    await screen.findByText('Feld current-filter');
    expect(originalSignal.aborted).toBe(true);
    await act(async () => resolveOld({ items: [row('stale')], next_cursor: null }));
    expect(screen.queryByText('Feld stale')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Neueste Änderungen' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Die Änderungsseite ist unvollständig.');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
});
