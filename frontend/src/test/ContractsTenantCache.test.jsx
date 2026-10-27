import { useState } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api';
import { DataStoreProvider } from '../contexts/DataStoreContext';
import Contracts from '../pages/Contracts';
import Tenants from '../pages/Tenants';

vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => ({
  'ui.buttons.new': 'Neu', 'ui.buttons.edit': 'Bearbeiten', 'ui.buttons.save': 'Speichern',
  'ui.buttons.cancel': 'Abbrechen', 'ui.buttons.close': 'Schließen',
  'tenantsContracts.contracts.occupants.action': 'Bewohner',
}[key]), locale: 'de-DE' }) }));
vi.mock('../components/Toast', () => ({ useToast: () => ({ error: vi.fn(), success: vi.fn() }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => async () => true }));
vi.mock('../features/partyWorkspace/PartyWorkspace', () => ({
  PartyLink: ({ children }) => <button>{children}</button>,
  usePartyWorkspace: () => ({ openParty: vi.fn() }),
}));

function Pages() {
  const [page, setPage] = useState('contracts');
  return <MemoryRouter><DataStoreProvider>
    <button onClick={() => setPage('contracts')}>Zur Vertragsseite</button>
    <button onClick={() => setPage('tenants')}>Zur Mieterseite</button>
    {page === 'contracts' ? <Contracts /> : <Tenants />}
  </DataStoreProvider></MemoryRouter>;
}

let tenants;
beforeEach(() => {
  vi.resetAllMocks();
  // Keep the cache inside its TTL for the entire navigation/mutation sequence.
  vi.spyOn(Date, 'now').mockReturnValue(1_800_000_000_000);
  tenants = [{ id: 'tenant', full_name: 'Bisherige Partei', archived: false }];
  api.list.mockImplementation(async path => {
    if (path === '/tenants?include_archived=true') return tenants.map(row => ({ ...row }));
    if (path === '/contracts') return [{ id: 'contract', contract_number: 'MV-1', tenant_id: 'tenant',
      property_id: 'p1', unit_id: 'u1', status: 'active', start_date: '2026-01-01' }];
    if (path === '/properties') return [{ id: 'p1', name: 'Haus' }];
    if (path === '/units') return [{ id: 'u1', label: 'Wohnung', property_id: 'p1' }];
    throw new Error(`Unexpected list: ${path}`);
  });
  api.get.mockResolvedValue({});
  api.post.mockImplementation(async (path, data) => {
    if (path !== '/tenants') throw new Error(`Unexpected post: ${path}`);
    const saved = { ...data, id: 'new', archived: false };
    tenants = [...tenants, saved];
    return saved;
  });
  api.put.mockImplementation(async (path, data) => {
    if (path !== '/tenants/tenant') throw new Error(`Unexpected put: ${path}`);
    tenants = tenants.map(row => row.id === 'tenant' ? { ...row, ...data } : row);
    return tenants[0];
  });
  api.patch.mockImplementation(async path => {
    if (path !== '/tenants/tenant/archive') throw new Error(`Unexpected patch: ${path}`);
    tenants = tenants.map(row => ({ ...row, archived: true }));
    return tenants[0];
  });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('contract tenant cache across page mutations', () => {
  it('limits units to the selected property and clears the old unit when the property changes', async () => {
    const previous = api.list.getMockImplementation();
    api.list.mockImplementation(async path => {
      if (path === '/properties') return [{ id: 'p1', name: 'Haus A' }, { id: 'p2', name: 'Haus B' }];
      if (path === '/units') return [{ id: 'u1', label: 'Wohnung', property_id: 'p1' },
        { id: 'u2', label: 'Wohnung', property_id: 'p2' }, { id: 'u3', label: 'Dachwohnung', property_id: 'p2' }];
      return previous(path);
    });
    render(<Pages />);
    await screen.findByText('MV-1');
    fireEvent.click(screen.getByRole('button', { name: 'Neu' }));
    const property = screen.getByLabelText('Immobilie *'), unit = screen.getByLabelText('Einheit *');
    fireEvent.change(property, { target: { value: 'p1' } });
    await waitFor(() => expect(unit).toHaveValue('u1'));
    expect(within(unit).queryByRole('option', { name: 'Wohnung · Haus B' })).not.toBeInTheDocument();
    fireEvent.change(property, { target: { value: 'p2' } });
    expect(unit).toHaveValue('');
    expect(within(unit).queryByRole('option', { name: 'Wohnung · Haus A' })).not.toBeInTheDocument();
    fireEvent.change(unit, { target: { value: 'u3' } });
    expect(property).toHaveValue('p2');
  });
  it.each(['create', 'rename', 'archive'])('reflects a tenant %s before the cache expires', async mutation => {
    render(<Pages />);
    await screen.findByRole('button', { name: 'Bisherige Partei' });
    fireEvent.click(screen.getByRole('button', { name: 'Zur Mieterseite' }));
    await screen.findByRole('button', { name: 'Bisherige Partei' });

    if (mutation === 'archive') {
      // Drain confirmation, mutation and the immediate mocked source reloads.
      // A transient loading screen alone does not prove archival completed.
      await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Archivieren' })); });
      expect(api.patch).toHaveBeenCalledExactlyOnceWith('/tenants/tenant/archive', {});
      expect(within(screen.getByRole('button', { name: 'Archiviert: Quellvorgänge anzeigen' })).getByText('1')).toBeInTheDocument();
      await waitFor(() => expect(screen.queryByRole('button', { name: 'Bisherige Partei' })).not.toBeInTheDocument());
    } else {
      fireEvent.click(screen.getByRole('button', { name: mutation === 'create' ? 'Partei anlegen' : 'Bearbeiten' }));
      fireEvent.change(screen.getByLabelText('Vollständiger Name *'), { target: { value: 'Neue Partei' } });
      fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
      await screen.findByRole('button', { name: 'Neue Partei' });
    }

    fireEvent.click(screen.getByRole('button', { name: 'Zur Vertragsseite' }));
    await screen.findByText('MV-1');
    if (mutation === 'rename') await screen.findByRole('button', { name: 'Neue Partei' });
    // Contract rows and their separately cached party names resolve independently.
    if (mutation === 'archive') await screen.findByRole('button', { name: 'Bisherige Partei' });
    fireEvent.click(screen.getByRole('button', { name: 'Neu' }));
    const select = screen.getByLabelText('Mieter *');
    if (mutation === 'archive') {
      expect(within(select).queryByRole('option', { name: 'Bisherige Partei' })).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'Abbrechen' }));
      fireEvent.click(screen.getByRole('button', { name: 'Bearbeiten' }));
      expect(within(screen.getByLabelText('Mieter *')).getByRole('option', { name: 'Bisherige Partei (archiviert)' })).toHaveValue('tenant');
    } else {
      expect(within(select).getByRole('option', { name: 'Neue Partei' })).toHaveValue(mutation === 'create' ? 'new' : 'tenant');
      if (mutation === 'rename') expect(within(select).queryByRole('option', { name: 'Bisherige Partei' })).not.toBeInTheDocument();
    }
  });
});
