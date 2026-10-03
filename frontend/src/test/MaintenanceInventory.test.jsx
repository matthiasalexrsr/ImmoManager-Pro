import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import german from '../../../i18n/de-DE.json';
import Maintenance from '../pages/Maintenance';

const mocks = vi.hoisted(() => ({ get: vi.fn(), getBlob: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), user: null }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: mocks.user }) }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => null }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => vi.fn().mockResolvedValue(true) }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: 'de-DE', t: key => key.split('.').reduce((value, part) => value?.[part], german) || key }) }));
const row = (id = 'case-a', title = 'Heizung prüfen') => ({ id, title, property_id: 'property-a', unit_id: 'unit-a', property_name: 'Lindenhof', unit_label: 'Gartenwohnung',
  category: 'Heizung', priority: 'high', status: 'open', due_date: '2026-01-01', appointment_at: '2026-01-01T15:30:00', estimated_cost: 0, assignee: 'Maria', contractor: 'Betrieb Müller', reported_by: 'Mietpartei',
  created_at: '2026-01-01T00:00:00', updated_at: '2026-10-03T00:00:00.000001Z', edit_etag: 'case-revision' });
const page = (items, cursor = null) => ({ items, has_more: Boolean(cursor), next_cursor: cursor });
const totals = { total: 10025, open: 10024, in_progress: 1, overdue: 10, no_appointment: 301, no_assignee: 12, as_of: '2026-10-03' };
const response = path => path.includes('/summary?') ? totals : path.startsWith('/workflow-references/')
  ? { ...page([{ id: 'property-a', name: 'Lindenhof' }]), selected: { id: 'selected', name: 'Bestehende Zuordnung' } }
  : path.startsWith('/maintenance/inventory/') ? page([row()]) : { ...row(), description: 'Vollständiger Bericht' };
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };

beforeEach(() => {
  Object.values(mocks).forEach(value => value?.mockReset?.());
  mocks.user = { id: 'owner', role: 'eigentuemer', portfolio_access: 'all', portfolio_ids: [] };
  mocks.get.mockImplementation(path => Promise.resolve(response(path)));
});

describe('complete maintenance case inventory', () => {
  it('shows full counts, explicit date, actual appointment time and zero estimate', async () => {
    render(<Maintenance />); await screen.findByText('Heizung prüfen');
    expect(screen.getByRole('region', { name: 'Kennzahlen der gefilterten Wartungsfälle' })).toHaveTextContent('10025');
    expect(screen.getByRole('table')).toHaveTextContent('15:30');
    expect(screen.getByRole('table')).toHaveTextContent('0,00');
    expect(screen.getByRole('table')).toHaveTextContent('Betrieb Müller');
    expect(screen.getByRole('combobox', { name: 'Sortierung', exact: true })).toHaveValue('due_date');
    expect(mocks.get.mock.calls.every(([path]) => path.includes('/inventory/') || path.includes('/workflow-references/'))).toBe(true);
    expect(mocks.get.mock.calls.find(([path]) => path.includes('/inventory/page?'))[0]).toContain('as_of=');
  });

  it('loads later pages from server and preserves failed search input', async () => {
    mocks.get.mockImplementation(path => path.includes('search=Ausfall') ? Promise.reject(new Error('Server vorübergehend nicht erreichbar')) : Promise.resolve(path.includes('/page?')
      ? path.includes('cursor=later') ? page([row('later', 'Späterer Fall')]) : page([row()], 'later') : response(path)));
    render(<Maintenance />); await screen.findByText('Heizung prüfen');
    await userEvent.click(screen.getByRole('button', { name: 'Nächste Seite', exact: true }));
    expect(await screen.findByText('Späterer Fall')).toBeVisible();
    fireEvent.change(screen.getByRole('searchbox', { name: 'Wartungsfälle durchsuchen' }), { target: { value: 'Ausfall' } });
    await screen.findAllByText(/Server vorübergehend/);
    expect(screen.getByRole('searchbox', { name: 'Wartungsfälle durchsuchen' })).toHaveValue('Ausfall');
    expect(screen.queryByText('Keine passenden Wartungsfälle auf dieser Seite.')).not.toBeInTheDocument();
  });

  it('loads full case before edit and retains fields, precise appointment and revision after failure', async () => {
    mocks.put.mockRejectedValue(new Error('Speichern vorübergehend gesperrt'));
    render(<Maintenance />); await screen.findByText('Heizung prüfen');
    await userEvent.click(screen.getByRole('button', { name: 'Heizung prüfen bearbeiten' }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByLabelText('Beschreibung')).toHaveValue('Vollständiger Bericht');
    expect(within(dialog).getByLabelText('Termin mit Uhrzeit')).toHaveValue('2026-01-01T15:30');
    fireEvent.change(within(dialog).getByLabelText('Titel *'), { target: { value: 'Erhaltener Auftrag' } });
    fireEvent.submit(dialog.querySelector('form'));
    expect(await within(dialog).findByText('Speichern vorübergehend gesperrt')).toBeVisible();
    expect(within(dialog).getByLabelText('Titel *')).toHaveValue('Erhaltener Auftrag');
    expect(mocks.put.mock.calls[0][1]).toMatchObject({ property_id: 'property-a', unit_id: 'unit-a', description: 'Vollständiger Bericht', appointment_at: '2026-01-01T15:30:00', estimated_cost: 0 });
    expect(mocks.put.mock.calls[0][2].ifMatch.updatedAt).toBe(row().updated_at);
  });

  it.each(['user', 'scope', 'role'])('drops private page and pending edit on %s change', async kind => {
    const rendered = render(<Maintenance />); await screen.findByText('Heizung prüfen');
    const pending = deferred(); mocks.get.mockImplementation(path => path === '/maintenance/case-a' ? pending.promise : new Promise(() => {}));
    await userEvent.click(screen.getByRole('button', { name: 'Heizung prüfen bearbeiten' }));
    const signal = mocks.get.mock.calls.find(([path]) => path === '/maintenance/case-a')[1].signal;
    if (kind === 'user') mocks.user = { ...mocks.user, id: 'other' };
    if (kind === 'scope') mocks.user = { ...mocks.user, portfolio_ids: ['other'] };
    if (kind === 'role') mocks.user = { ...mocks.user, role: 'readonly' };
    rendered.rerender(<Maintenance />);
    expect(screen.queryByText('Heizung prüfen')).not.toBeInTheDocument(); expect(signal.aborted).toBe(true);
    await act(async () => pending.resolve(response('/maintenance/case-a')));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('rejects old response after changing search', async () => {
    const old = deferred(); mocks.get.mockImplementation(path => path.includes('/page?') && !path.includes('search=') ? old.promise : Promise.resolve(response(path)));
    render(<Maintenance />); fireEvent.change(screen.getByRole('searchbox', { name: 'Wartungsfälle durchsuchen' }), { target: { value: 'Neu' } });
    await screen.findByText('Heizung prüfen');
    await act(async () => old.resolve(page([row('old', 'Alter privater Fall')])));
    expect(screen.queryByText('Alter privater Fall')).not.toBeInTheDocument();
  });

  it('does not open an unexpected full-record reply', async () => {
    mocks.get.mockImplementation(path => Promise.resolve(path === '/maintenance/case-a' ? row('wrong', 'Foreign record') : response(path)));
    render(<Maintenance />); await screen.findByText('Heizung prüfen');
    await userEvent.click(screen.getByRole('button', { name: 'Heizung prüfen bearbeiten' }));
    expect(await screen.findByText('Der Wartungsfall konnte nicht geprüft werden.')).toBeVisible();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('shows failed counts independently while valid records remain usable', async () => {
    mocks.get.mockImplementation(path => path.includes('/summary?') ? Promise.reject(new Error('Kennzahlenserver nicht erreichbar')) : Promise.resolve(response(path)));
    render(<Maintenance />); await screen.findByText('Heizung prüfen');
    const summary = screen.getByRole('region', { name: 'Kennzahlen der gefilterten Wartungsfälle' });
    expect(summary).toHaveTextContent('Kennzahlen nicht verfügbar.');
    expect(summary).not.toHaveTextContent('10025');
  });

  it('offers readers filtering and exports without write actions', async () => {
    mocks.user = { ...mocks.user, role: 'readonly' };
    render(<Maintenance />); await screen.findByText('Heizung prüfen');
    expect(screen.queryByRole('button', { name: 'Wartungsfall anlegen' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Heizung prüfen bearbeiten' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Alle gefilterten Wartungsfälle exportieren' })).toBeVisible();
  });

  it('exports complete query and shows interruption without destroying filters', async () => {
    mocks.getBlob.mockRejectedValue(new Error('Export unterbrochen'));
    render(<Maintenance />); await screen.findByText('Heizung prüfen');
    fireEvent.change(screen.getByRole('searchbox', { name: 'Wartungsfälle durchsuchen' }), { target: { value: 'Heizung' } });
    await userEvent.click(screen.getByRole('button', { name: 'Alle gefilterten Wartungsfälle exportieren' }));
    expect(await screen.findByText('Export unterbrochen')).toBeVisible();
    expect(mocks.getBlob.mock.calls[0][0]).toContain('search=Heizung');
    expect(mocks.getBlob.mock.calls[0][0]).not.toContain('cursor=');
  });
});
