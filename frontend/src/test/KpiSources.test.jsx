import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { api } from '../api';
import Tasks from '../pages/Tasks';
import Maintenance from '../pages/Maintenance';
import Statements from '../pages/Statements';
import Messages from '../pages/Messages';

vi.mock('../api', () => ({ api: { captureSession: vi.fn(), get: vi.fn(), list: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), del: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: () => undefined, locale: 'de-DE' }) }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => null, useCanWrite: () => false }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => null, useEntities: () => ({ items: [] }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => async () => true }));
vi.mock('../components/Toast', () => ({ useToast: () => ({ error: vi.fn(), success: vi.fn() }) }));
vi.mock('../features/partyWorkspace/PartyWorkspace', () => ({ PartyLink: ({ children }) => <span>{children}</span> }));
const task = (id, status, due_date, extra = {}) => ({ id, title: id, status, due_date, priority: 'medium', property_id: 'p1', ...extra });
const rows = [task('Offener Rückruf', 'open', '2026-10-14'), task('Laufende Prüfung', 'in_progress', '2026-10-16'),
  task('Erledigte Prüfung', 'completed', '2026-10-01'), task('Abgesagter Termin', 'cancelled', '2026-10-01'),
  task('Serienkontrolle', 'open', '2026-10-20', { recurrence_rule: 'FREQ=WEEKLY' }), task('Anderes Objekt', 'open', '2026-10-01', { property_id: 'p2' })];
const show = (component, path) => render(<MemoryRouter initialEntries={[path]}>{component}</MemoryRouter>);
beforeEach(() => {
  vi.resetAllMocks(); localStorage.clear(); sessionStorage.clear();
  vi.useFakeTimers({ toFake: ['Date'] }); vi.setSystemTime(new Date(2026, 9, 15, 12));
  api.captureSession.mockReturnValue(() => {});
  api.list.mockResolvedValue([]);
  // The personal inbox mounted inside Messages has its own paginated API
  // contract. It must not receive the unrelated generic {} fixture.
  api.get.mockImplementation(async path => path.startsWith('/notifications/inbox?')
    ? { items: [], total: 0, unread_count: 0, next_cursor: null, snapshot: 'synthetic-inbox' }
    : {});
  api.patch.mockResolvedValue({});
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe('exact KPI source lists', () => {
  it('adopts task status and property links and clears a table search when opening a KPI source', async () => {
    api.list.mockResolvedValue(rows);
    show(<Tasks />, '/tasks?status=open&property_id=p1');
    await screen.findByText('Offener Rückruf');
    expect(screen.getByText('Serienkontrolle')).toBeInTheDocument();
    expect(screen.queryByText('Laufende Prüfung')).not.toBeInTheDocument();
    expect(screen.queryByText('Anderes Objekt')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'In Bearbeitung: Quellvorgänge anzeigen' }));
    expect(screen.getByText('Laufende Prüfung')).toBeInTheDocument();
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Nicht vorhanden' } });
    expect(screen.queryByText('Laufende Prüfung')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Überfällig: Quellvorgänge anzeigen' }));
    expect(screen.getByText('Offener Rückruf')).toBeInTheDocument();
    expect(screen.queryByText('Abgesagter Termin')).not.toBeInTheDocument();
    expect(screen.queryByText('Erledigte Prüfung')).not.toBeInTheDocument();
    expect(screen.queryByText('Anderes Objekt')).not.toBeInTheDocument();
  });

  it('uses the dashboard overdue maintenance statuses and the original age-average source', async () => {
    const cases = [task('Offene Reparatur', 'open', '2026-10-14'), task('Prüfung ausstehend', 'pending', '2026-10-14'),
      task('In Prüfung', 'review', '2026-10-14'), task('Heute fällig', 'in_progress', '2026-10-15'), task('Abgeschlossen', 'completed', '2026-10-14')];
    api.list.mockResolvedValue(cases);
    show(<Maintenance />, '/maintenance?filter=overdue');
    await screen.findByText('Offene Reparatur');
    expect(screen.getByText('Prüfung ausstehend')).toBeInTheDocument();
    expect(screen.getByText('In Prüfung')).toBeInTheDocument();
    expect(screen.queryByText('Heute fällig')).not.toBeInTheDocument();
    expect(screen.queryByText('Abgeschlossen')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Ø Alter (offen / in Bearbeitung): Quellvorgänge anzeigen' }));
    expect(screen.getByText('Offene Reparatur')).toBeInTheDocument();
    expect(screen.getByText('Heute fällig')).toBeInTheDocument();
    expect(screen.queryByText('Prüfung ausstehend')).not.toBeInTheDocument();
  });

  it('uses the server-selected escalation cases and retains a source error for retry', async () => {
    const escalated = task('Regelgrenze erreicht', 'review', '2026-10-14');
    let fail = true;
    api.list.mockImplementation(async path => {
      if (path.includes('workflow_filter=escalation')) { if (fail) throw new Error('Regelquelle offline'); return [escalated]; }
      return [escalated, task('Keine Regel erreicht', 'open', '2026-10-14')];
    });
    show(<Maintenance />, '/maintenance?filter=escalation');
    expect(await screen.findByRole('alert')).toHaveTextContent('Regelquelle offline');
    expect(screen.queryByText('Keine Regel erreicht')).not.toBeInTheDocument();
    fail = false; fireEvent.click(screen.getByRole('button', { name: 'Eskalationsquelle erneut laden' }));
    expect(await screen.findByText('Regelgrenze erreicht')).toBeInTheDocument();
    expect(screen.queryByText('Keine Regel erreicht')).not.toBeInTheDocument();
  });

  it('opens the exact preflight periods and separately exposes every counted utility statement', async () => {
    const periods = [{ id: 'b1', property_id: 'p1', start_date: '2025-01-01', end_date: '2025-12-31', status: 'draft' },
      { id: 'b2', property_id: 'p2', start_date: '2024-01-01', end_date: '2024-12-31', status: 'review' }];
    api.list.mockImplementation(async path => ({ '/billing/periods': periods,
      '/billing/periods?workflow_filter=preflight_blockers': [periods[1]],
      '/properties': [{ id: 'p1', name: 'Ohne Fehler' }, { id: 'p2', name: 'Mit Fehler' }],
      '/billing/statements': [{ id: 's1', billing_period_id: 'b1', unit_id: 'u1', party: 'vacancy', total_cost: 10 },
        { id: 's2', billing_period_id: 'b2', unit_id: 'u2', party: 'vacancy', total_cost: 20 }],
      '/units': [{ id: 'u1', label: 'Einzelabrechnung A' }, { id: 'u2', label: 'Einzelabrechnung B' }],
    }[path] || []));
    show(<Statements />, '/statements?filter=preflight_blockers');
    expect(await screen.findByText('Mit Fehler')).toBeInTheDocument();
    expect(screen.queryByText('Ohne Fehler')).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Quelle'), { target: { value: 'statements' } });
    expect(screen.getByText('Einzelabrechnung A')).toBeInTheDocument();
    expect(screen.getByText('Einzelabrechnung B')).toBeInTheDocument();
  });

  it('shows only unread personal notices and retains them after a failed receipt command', async () => {
    const unread = { id: 'n1', title: 'Offener Hinweis', content: 'Synthetische Akte',
      status: 'unread', severity: 'warning', email_eligible: false, archived_at: null,
      created_at: '2026-10-15T08:00:00Z', target: null, target_error: 'Keine Quelle' };
    api.get.mockImplementation(async path => path.startsWith('/notifications/inbox?')
      ? { items: [unread], total: 1, unread_count: 1, snapshot: 'synthetic-scope-snapshot', next_cursor: null }
      : {});
    api.post.mockRejectedValue(new Error('Lesestatus nicht gespeichert'));
    show(<Messages />, '/messages?status=unread');
    expect(await screen.findByText('Offener Hinweis')).toBeInTheDocument();
    expect(screen.queryByText('Gelesener Hinweis')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Alle berechtigten Hinweise gelesen archivieren' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Lesestatus nicht gespeichert');
    expect(screen.getByText('Offener Hinweis')).toBeInTheDocument();
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/notifications/all/receipt',
      expect.objectContaining({ action: 'read_all', snapshot: 'synthetic-scope-snapshot',
        base_revision: 0, idempotency_key: expect.any(String) })));
    // An unconfirmed server write must not locally delete or archive a notice.
    expect(screen.queryByText('Keine Hinweise in dieser Ansicht.')).not.toBeInTheDocument();
  });
});
