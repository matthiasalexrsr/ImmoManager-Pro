import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import History from '../pages/History';

const mocks = vi.hoisted(() => ({ get: vi.fn(), getBlob: vi.fn(), updateUser: vi.fn(), user: null }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: mocks.user, updateUser: mocks.updateUser }) }));
const actor = { id: 'reader', role: 'readonly', portfolio_access: 'selected', portfolio_ids: ['portfolio-a'], write_permissions: [] };
const row = (id = 'history-a', value = 'Vollständiger ursprünglicher Wert mit Umlauten äöü') => ({
  id, entity_type: 'property', entity_id: 'property-a', field_name: 'name', changed_by: 'actor-id',
  old_value: value, new_value: 'Nachher', reason: 'Ergänzung mit Grund', changed_at: '2026-10-03T11:00:00.000001',
});
const page = (items = [row()], cursor = null) => ({ items, has_more: cursor !== null, next_cursor: cursor });
function deferred() { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; }

beforeEach(() => {
  vi.clearAllMocks(); mocks.user = actor;
  mocks.get.mockImplementation(path => Promise.resolve(path === '/auth/me' ? mocks.user : path.includes('/summary?') ? { total: 10002 } : page()));
  mocks.getBlob.mockResolvedValue(new Blob(['synthetic-csv']));
});

describe('Complete personal authority-bound change history', () => {
  it('uses bounded pages and full counts and renders complete original values', async () => {
    const longValue = 'Ursprünglicher Wert '.repeat(30);
    mocks.get.mockImplementation(path => Promise.resolve(path === '/auth/me' ? mocks.user : path.includes('/summary?') ? { total: 10002 } : page([row('history-long', longValue)])));
    render(<History />);
    expect(await screen.findByText('10.002')).toBeVisible();
    fireEvent.click(screen.getByText('Werte und Grund anzeigen'));
    expect(screen.getByText(longValue.trim())).toBeVisible();
    expect(screen.getByText('Ergänzung mit Grund')).toBeVisible();
    expect(mocks.get.mock.calls.some(([path]) => path.includes('/history/inventory/page?') && path.includes('page_size=25'))).toBe(true);
    expect(mocks.get.mock.calls.some(([path]) => path.includes('limit=500') || path.includes('/properties'))).toBe(false);
  });

  it('keeps filters and distinguishes failure from a verified empty page', async () => {
    let fail = true;
    mocks.get.mockImplementation(path => path === '/auth/me' ? Promise.resolve(mocks.user) : path.includes('/summary?') ? Promise.resolve({ total: 0 })
      : fail ? Promise.reject(new Error('Verbindung unterbrochen')) : Promise.resolve(page([])));
    render(<History />);
    expect(await screen.findByText('Verbindung unterbrochen')).toBeVisible();
    expect(screen.queryByText('Keine passenden Änderungen auf dieser Seite.')).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole('searchbox', { name: 'Historie durchsuchen' }), { target: { value: 'Müller' } });
    await screen.findByText('Verbindung unterbrochen');
    fail = false;
    fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
    expect(await screen.findByText('Keine passenden Änderungen auf dieser Seite.')).toBeVisible();
    expect(screen.getByRole('searchbox')).toHaveValue('Müller');
  });

  it('reaches opaque next pages and exports the full query without the cursor', async () => {
    mocks.getBlob.mockRejectedValue(new Error('Export unterbrochen'));
    mocks.get.mockImplementation(path => Promise.resolve(path === '/auth/me' ? mocks.user : path.includes('/summary?') ? { total: 10002 }
      : path.includes('cursor=opaque-next') ? page([row('history-next')]) : page([row()], 'opaque-next')));
    render(<History />); await screen.findByText('actor-id');
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'Müller' } });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Nächste Seite' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Nächste Seite' }));
    expect(await screen.findByText('Seite 2')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Alle gefilterten Änderungen exportieren' }));
    expect(await screen.findByText('Export unterbrochen')).toBeVisible();
    expect(mocks.getBlob.mock.calls[0][0]).toContain('search=M%C3%BCller');
    expect(mocks.getBlob.mock.calls[0][0]).not.toContain('cursor=');
  });

  it('discards a delayed old filter response and aborts its request', async () => {
    const old = deferred(); let oldSignal;
    mocks.get.mockImplementation((path, options) => path === '/auth/me' ? Promise.resolve(mocks.user) : path.includes('/summary?') ? Promise.resolve({ total: 1 })
      : path.includes('search=neuer') ? Promise.resolve(page([row('new', 'Neue Auswahl')])) : (oldSignal = options.signal, old.promise));
    render(<History />); await screen.findByRole('searchbox');
    await waitFor(() => expect(oldSignal).toBeDefined());
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'neuer' } });
    await screen.findByText('actor-id');
    await act(async () => old.resolve(page([row('old', 'Alte private Auswahl')])));
    expect(oldSignal.aborted).toBe(true); expect(screen.queryByText('Alte private Auswahl')).not.toBeInTheDocument();
  });

  it('removes old private rows synchronously on actor change', async () => {
    const { rerender } = render(<History />); await screen.findByText('actor-id');
    const gate = deferred(); mocks.get.mockImplementation(() => gate.promise);
    mocks.user = { ...actor, id: 'other' }; rerender(<History />);
    expect(screen.queryByText('actor-id')).not.toBeInTheDocument();
    expect(screen.getByText('Zugriff wird geprüft …')).toBeVisible();
  });

  it('hides stale data during same-actor focus validation and blocks a changed grant', async () => {
    render(<History />); await screen.findByText('actor-id');
    const gate = deferred(); mocks.get.mockImplementation(path => path === '/auth/me' ? gate.promise : Promise.resolve(page()));
    fireEvent.focus(window);
    expect(screen.queryByText('actor-id')).not.toBeInTheDocument();
    await act(async () => gate.resolve({ ...actor, portfolio_ids: [] }));
    expect(await screen.findByText('Die Zugriffsrechte wurden geändert. Bitte die Historie neu öffnen.')).toBeVisible();
    expect(mocks.updateUser).toHaveBeenCalledWith({ ...actor, portfolio_ids: [] });
    expect(mocks.getBlob).not.toHaveBeenCalled();
  });

  it('neutralizes a successful page when the independent count reports lost access', async () => {
    mocks.get.mockImplementation(path => path === '/auth/me' ? Promise.resolve(mocks.user) : path.includes('/summary?')
      ? Promise.reject(Object.assign(new Error('Denied'), { statusCode: 403 })) : Promise.resolve(page()));
    render(<History />);
    expect(await screen.findByText('Der Zugriff wurde geändert oder die Daten sind nicht verfügbar.')).toBeVisible();
    expect(screen.queryByText('actor-id')).not.toBeInTheDocument();
    expect(screen.queryByText('0')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Alle gefilterten Änderungen exportieren' })).toBeDisabled();
  });
});
