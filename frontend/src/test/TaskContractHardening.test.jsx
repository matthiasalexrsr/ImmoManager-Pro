import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Tasks from '../pages/Tasks';
import Contracts from '../pages/Contracts';
import { api } from '../api';

const context = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn(), invalidate: vi.fn(), openParty: vi.fn(), lookups: {} }));
vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), del: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => ({ 'ui.buttons.save': 'Speichern', 'ui.buttons.cancel': 'Abbrechen', 'ui.buttons.close': 'Schließen' }[key]), locale: 'de-DE' }) }));
vi.mock('../components/Toast', () => ({ useToast: () => ({ error: context.error, success: context.success }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => async () => true }));
vi.mock('../contexts/DataStoreContext', () => ({
  useDataStore: () => ({ invalidateRelated: context.invalidate }),
  useEntities: (key, endpoint) => ({ items: key.startsWith('tenant')
    ? context.lookups.tenants.filter(row => !row.archived || endpoint.includes('include_archived=true'))
    : context.lookups[key] || [], loading: false, error: null, reload: vi.fn() }),
}));
vi.mock('../features/partyWorkspace/PartyWorkspace', () => ({ PartyLink: ({ tenantId, children }) =>
  <button onClick={() => context.openParty(tenantId)}>{children}</button> }));
vi.mock('../components/DataTable', () => ({ default: ({ data, columns, onAdd, onEdit, onDelete, rowActions }) => <div>
  <button onClick={onAdd}>Hinzufügen</button>
  {data.map(row => <div key={row.id} data-testid={row.id}>
    {columns.filter(col => !col.hidden).map(col => <span key={col.key}>{col.render ? col.render(row[col.key], row) : row[col.key]}</span>)}
    <button onClick={() => onEdit(row)}>Bearbeiten</button>
    <button onClick={() => onDelete(row)}>Löschen</button>
    {rowActions?.(row).map(action => <button key={action.label} onClick={() => action.onClick(row)}>{action.label}</button>)}
  </div>)}
  </div> }));

const task = { id: 'child', title: 'Serienkind', parent_task_id: 'template', property_id: 'p1', unit_id: 'u1',
  status: 'open', priority: 'medium', due_date: '2026-01-15', updated_at: '2026-10-07T10:00:00Z' };
const contract = { id: 'contract', contract_number: 'Historischer Vertrag', tenant_id: 'archived', unit_id: 'u1', property_id: 'p1', status: 'terminated' };

beforeEach(() => {
  vi.resetAllMocks();
  context.lookups = { properties: [{ id: 'p1', name: 'Haus A' }, { id: 'p2', name: 'Haus B' }],
    units: [{ id: 'u1', label: 'A1', property_id: 'p1' }, { id: 'u2', label: 'B1', property_id: 'p2' }],
    tenants: [{ id: 'archived', full_name: 'Archivierte Partei', archived: true }, { id: 'active', full_name: 'Aktive Partei', archived: false }] };
  api.get.mockResolvedValue({});
  api.list.mockImplementation(path => Promise.resolve(path === '/tasks' ? [task] : [contract]));
  api.patch.mockImplementation((_path, data) => Promise.resolve({ ...task, ...data, updated_at: '2026-10-07T11:00:00Z' }));
  api.post.mockResolvedValue({ created: [], errors: [] });
  api.del.mockResolvedValue(null);
});
afterEach(() => cleanup());

describe('task hardening', () => {
  it('shows list failure and retries instead of displaying an empty success', async () => {
    api.list.mockRejectedValueOnce(new Error('Aufgaben nicht erreichbar'));
    render(<Tasks />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Aufgaben nicht erreichbar');
    fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
    expect(await screen.findByText('Serienkind')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('edits with PATCH and preserves the series relationship and revision', async () => {
    render(<Tasks />);
    await screen.findByText('Serienkind');
    fireEvent.click(screen.getByRole('button', { name: 'Bearbeiten' }));
    fireEvent.change(screen.getByLabelText('Titel *'), { target: { value: 'Geändert' } });
    fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/tasks/child', expect.objectContaining({ title: 'Geändert', updated_at: task.updated_at })));
    expect(api.patch.mock.calls[0][1]).not.toHaveProperty('parent_task_id');
    expect(api.put).not.toHaveBeenCalled();
  });

  it('filters unit options by property and clears the old unit when property changes', async () => {
    render(<Tasks />);
    await screen.findByText('Serienkind');
    fireEvent.click(screen.getByRole('button', { name: 'Bearbeiten' }));
    const unitSelect = screen.getByLabelText('Einheit');
    expect(within(unitSelect).queryByRole('option', { name: 'B1' })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Immobilie'), { target: { value: 'p2' } });
    expect(unitSelect).toHaveValue('');
    expect(within(unitSelect).getByRole('option', { name: 'B1' })).toBeInTheDocument();
    expect(within(unitSelect).queryByRole('option', { name: 'A1' })).not.toBeInTheDocument();
  });

  it('completes and reopens with returned revision while retaining rows on refresh failure', async () => {
    render(<Tasks />);
    await screen.findByText('Serienkind');
    api.list.mockRejectedValue(new Error('Aktualisierung fehlgeschlagen'));
    fireEvent.click(screen.getByRole('button', { name: 'Erledigen' }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/tasks/child', { status: 'completed', updated_at: task.updated_at }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Aktualisierung fehlgeschlagen');
    expect(screen.getByText('Serienkind')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Wiederöffnen' }));
    await waitFor(() => expect(api.patch).toHaveBeenLastCalledWith('/tasks/child', { status: 'open', updated_at: '2026-10-07T11:00:00Z' }));
  });

  it('shows quick action conflicts and deletion errors without losing the task', async () => {
    render(<Tasks />);
    await screen.findByText('Serienkind');
    api.patch.mockRejectedValue(new Error('Datensatz wurde inzwischen geändert'));
    fireEvent.click(screen.getByRole('button', { name: 'Erledigen' }));
    await waitFor(() => expect(context.error).toHaveBeenCalledWith('Datensatz wurde inzwischen geändert'));
    expect(screen.getByText('Serienkind')).toBeInTheDocument();
    api.del.mockRejectedValue(new Error('Löschen fehlgeschlagen'));
    fireEvent.click(screen.getByRole('button', { name: 'Löschen' }));
    await waitFor(() => expect(context.error).toHaveBeenCalledWith('Löschen fehlgeschlagen'));
    expect(screen.getByText('Serienkind')).toBeInTheDocument();
  });

  it('shows per-series generation errors alongside successful children', async () => {
    api.post.mockResolvedValue({ created: [{ ...task, id: 'next', title: 'Neue Folge' }],
      errors: [{ task_id: 'bad', title: 'Alte Serie', error: 'INTERVAL muss positiv sein' }] });
    render(<Tasks />);
    await screen.findByText('Serienkind');
    fireEvent.click(screen.getByRole('button', { name: 'Folgeaufgaben erzeugen' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/tasks/generate-recurring/report', {}));
    expect(await screen.findByRole('alert')).toHaveTextContent('Alte Serie: INTERVAL muss positiv sein');
    expect(context.success).toHaveBeenCalledWith('1 Folgeaufgabe erzeugt');
  });
});

describe('historical contracts', () => {
  it('keeps archived parties named and reachable through their party workspace', async () => {
    render(<Contracts />);
    fireEvent.click(await screen.findByRole('button', { name: 'Archivierte Partei' }));
    expect(context.openParty).toHaveBeenCalledWith('archived');
    fireEvent.click(screen.getByRole('button', { name: 'Bearbeiten' }));
    expect(within(screen.getByLabelText('Mieter *')).getByRole('option', { name: /Archivierte Partei/ })).toHaveValue('archived');
  });

  it('shows contract load errors and retries', async () => {
    api.list.mockRejectedValueOnce(new Error('Verträge nicht erreichbar'));
    render(<Contracts />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Verträge nicht erreichbar');
    fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
    expect(await screen.findByText('Historischer Vertrag')).toBeInTheDocument();
  });

  it('retains current rent and contracts if a later refresh fails', async () => {
    api.get.mockResolvedValue({ contract: { cold_rent: 915 } });
    render(<Contracts />);
    await screen.findByText('Historischer Vertrag');
    api.list.mockRejectedValue(new Error('Verträge nicht erreichbar'));
    api.get.mockRejectedValue(new Error('Mieten nicht erreichbar'));
    api.put.mockResolvedValue(contract);
    fireEvent.click(screen.getByRole('button', { name: 'Bearbeiten' }));
    fireEvent.change(screen.getByLabelText('Vertragsnr. *'), { target: { value: 'Geändert' } });
    // Submit directly because the historic fixture deliberately has no start date.
    fireEvent.submit(screen.getByRole('dialog').querySelector('form'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Verträge nicht erreichbar');
    expect(screen.getByText('Historischer Vertrag')).toBeInTheDocument();
    expect(screen.getByText(/915/)).toBeInTheDocument();
  });
});
