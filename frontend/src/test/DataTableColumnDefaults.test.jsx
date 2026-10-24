import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import DataTable from '../components/DataTable';
import { columnHidden } from '../utils/tableSettings';
import { privateStorageKey } from '../utils/workspaceIdentity';
import { workspace } from '../utils/workspaceClient';

const auth = vi.hoisted(() => ({ owner: null }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => true, useAuth: () => auth.owner ? { user: { id: auth.owner } } : null }));
vi.mock('../utils/workspaceClient', async original => ({ ...await original(),
  workspace: { list: vi.fn(), get: vi.fn(), put: vi.fn(), command: () => crypto.randomUUID() } }));

// An update hid "Beleg" by default; "Notiz" was hidden by default before.
const columns = [
  { key: 'title', label: 'Bezeichnung' },
  { key: 'amount', label: 'Betrag' },
  { key: 'receipt', label: 'Beleg', hidden: true },
  { key: 'note', label: 'Notiz', hidden: true },
];
const data = [{ id: 'a', title: 'Alpha', amount: 5, receipt: 'ja', note: 'kurz' }];
const stored = settings => localStorage.setItem(privateStorageKey('table_settings:column-defaults'), JSON.stringify(settings));
const readStored = () => JSON.parse(localStorage.getItem(privateStorageKey('table_settings:column-defaults')));
const shown = () => within(screen.getByRole('table', { name: 'Vorgänge' })).getAllByRole('columnheader').map(th => th.textContent.replace(/[↕↑↓\s]+$/, ''));
const mount = () => render(<MemoryRouter initialEntries={['/maintenance']}>
  <DataTable title="Vorgänge" settingsKey="column-defaults" columns={columns} data={data} />
</MemoryRouter>);

beforeEach(() => { localStorage.clear(); sessionStorage.clear(); auth.owner = null; vi.clearAllMocks();
  workspace.list.mockResolvedValue({ items: [] }); workspace.get.mockResolvedValue(null); });
afterEach(cleanup);

describe('column defaults after an update', () => {
  it('keeps what a person chose and gives every other column its current default', () => {
    const receipt = columns[2], amount = columns[1], note = columns[3];
    // settings saved before defaults were recorded: everything counted as shown by default then
    expect(columnHidden(receipt, false, undefined)).toBe(true);     // shown only because it was the default
    expect(columnHidden(amount, true, undefined)).toBe(true);       // hidden by the person
    // recorded settings: a value that differed from the default of its time is a choice
    expect(columnHidden(note, false, ['note'])).toBe(false);        // shown by the person, stays shown
    expect(columnHidden(receipt, false, ['note'])).toBe(true);      // was the default, the new default applies
    expect(columnHidden(amount, true, ['amount'])).toBe(false);     // default hidden then, shown by default now
    expect(columnHidden(amount, false, [])).toBe(false);
  });

  it('applies new defaults to settings this browser kept from before the update', () => {
    stored({ hiddenCols: { title: false, amount: true, receipt: false, note: false } });
    mount();
    expect(shown()).toEqual(['Bezeichnung']);   // Betrag hidden by the person; Beleg and Notiz by default
  });

  it('keeps a column the person showed although it is hidden by default, and records the defaults', () => {
    stored({ hiddenCols: { title: false, amount: false, receipt: false, note: false }, hiddenDefaults: ['receipt', 'note'] });
    mount();
    expect(shown()).toEqual(['Bezeichnung', 'Betrag', 'Beleg', 'Notiz']);
    fireEvent.click(screen.getByRole('button', { name: 'ui.table.adjustColumns' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Notiz' }));
    expect(shown()).toEqual(['Bezeichnung', 'Betrag', 'Beleg']);
    expect(readStored()).toMatchObject({ hiddenCols: { receipt: false, note: true }, hiddenDefaults: ['receipt', 'note'] });
  });

  it('applies a saved view the same way and saves new views with their defaults', async () => {
    auth.owner = 'owner';
    workspace.list.mockResolvedValue({ items: [
      { id: 'before', name: 'Vor dem Update', config: { visible_columns: ['title', 'amount', 'receipt'], column_order: ['title', 'amount', 'receipt', 'note'] } },
      { id: 'chosen', name: 'Mit Beleg', config: { visible_columns: ['title', 'receipt'], hidden_defaults: ['receipt', 'note'],
        column_order: ['title', 'amount', 'receipt', 'note'] } },
    ] });
    workspace.put.mockImplementation(async (_kind, id, payload) => ({ id, revision: 1, ...payload }));
    mount();
    await screen.findByRole('option', { name: 'Vor dem Update' });
    fireEvent.change(screen.getByRole('combobox', { name: 'Ansicht' }), { target: { value: 'before' } });
    await waitFor(() => expect(shown()).toEqual(['Bezeichnung', 'Betrag']));
    fireEvent.change(screen.getByRole('combobox', { name: 'Ansicht' }), { target: { value: 'chosen' } });
    await waitFor(() => expect(shown()).toEqual(['Bezeichnung', 'Beleg']));

    fireEvent.change(screen.getByLabelText('Name der neuen Ansicht'), { target: { value: 'Neu' } });
    fireEvent.click(screen.getByText('Ansicht speichern'));
    await waitFor(() => expect(workspace.put).toHaveBeenCalled());
    const view = workspace.put.mock.calls.find(call => call[0] === 'views')[2];
    expect(view.config).toMatchObject({ visible_columns: ['title', 'receipt'], hidden_defaults: ['receipt', 'note'] });
  });

  it('shows the columns in the order of the program, not in an order a view froze', async () => {
    auth.owner = 'owner';
    workspace.list.mockResolvedValue({ items: [{ id: 'old', name: 'Alte Reihenfolge',
      config: { visible_columns: ['title', 'amount'], column_order: ['amount', 'title', 'receipt', 'note'] } }] });
    mount();
    await screen.findByRole('option', { name: 'Alte Reihenfolge' });
    fireEvent.change(screen.getByRole('combobox', { name: 'Ansicht' }), { target: { value: 'old' } });
    await waitFor(() => expect(shown()).toEqual(['Bezeichnung', 'Betrag']));
  });
});
