import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const authState = vi.hoisted(() => ({ user: null, write: null }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => authState, useCanWrite: () => true }));
vi.mock('../contexts/DataStoreContext', () => ({
  useDataStore: () => ({ invalidateRelated: vi.fn() }),
  useEntities: () => ({ items: [{ id: 'c-1', contract_number: 'V-1' }] }),
}));
vi.mock('../features/partyWorkspace/PartyWorkspace', () => ({ PartyLink: ({ children }) => <span>{children}</span> }));
vi.mock('../features/deposits/DepositFile', () => ({ default: ({ depositId }) => <div role="dialog" aria-label="Akte">Akte {depositId}</div> }));
vi.mock('../features/deposits/DepositsDialog', () => ({ default: ({ contractId }) => <div role="dialog" aria-label="Vertrag">Vertrag {contractId}</div> }));

import Deposits from '../pages/Deposits';

const row = index => ({ id: `d-${index}`, contract_id: 'c-1', contract_number: `V-${index}`, tenant_id: 't-1',
  tenant_name: `Mieter ${index}`, property_name: 'Bautzner Straße 61', unit_label: 'WE 3', form: 'transfer', amount: 1500,
  received: 1500, retention: index === 1 ? 300 : 0, stage: index === 1 ? 'retained' : 'received', contract_end: null });

describe('Deposits page', () => {
  beforeEach(() => { authState.user = { id: 'u-1', role: 'verwalter' }; authState.write = null; });

  it('lists the files of one page, counts all, filters and pages through the rest', async () => {
    const files = vi.fn(async ({ skip }) => ({
      items: Array.from({ length: skip ? 1 : 50 }, (_, i) => row(skip + i + 1)), total: 51, skip, limit: 50,
      totals: { count: 51, amount: 76500, received: 76500, retention: 300 }, stages: { retained: 1, received: 50 } }));
    render(<MemoryRouter><Deposits service={{ files }} /></MemoryRouter>);
    expect(await screen.findByText('51 Kautionen')).toBeInTheDocument();
    expect(screen.getByText('1–50 von 51')).toBeInTheDocument();
    expect(screen.getByText('Abgerechnet, Einbehalt offen')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Weiter' }));
    await waitFor(() => expect(files).toHaveBeenLastCalledWith(expect.objectContaining({ skip: 50 }), expect.anything()));
    expect(await screen.findByText('51–51 von 51')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Stand'), { target: { value: 'retained' } });
    await waitFor(() => expect(files).toHaveBeenLastCalledWith(expect.objectContaining({ stage: 'retained', skip: 0 }),
      expect.anything()));
    fireEvent.click(screen.getAllByRole('button', { name: /^Öffnen/ })[0]);
    expect(screen.getByRole('dialog', { name: 'Akte' })).toBeInTheDocument();
  });

  it('takes over the plain records of earlier versions after a confirmation', async () => {
    const files = vi.fn(async () => ({ items: [row(1)], total: 1, totals: { count: 1, amount: 1500, received: 0, retention: 0 }, stages: {} }));
    const legacyCandidates = vi.fn(async () => ({ count: 2, amount: 2400.5, items: [
      { id: 'd-1', contract_number: 'V-1', tenant_name: 'Mia Muster', amount: 1500, held_date: '2024-01-01' },
      { id: 'd-2', contract_number: 'V-2', tenant_name: 'Ben Berg', amount: 900.5, held_date: '2023-05-02' }] }));
    const takeOverLegacy = vi.fn(async () => ({ taken_over: 2 }));
    render(<MemoryRouter><Deposits service={{ files, legacyCandidates, takeOverLegacy }} /></MemoryRouter>);
    const panel = await screen.findByRole('region', { name: 'Kautionen aus dem bisherigen Datensatz' });
    expect(panel).toHaveTextContent(/2 Kautionen \(zusammen 2\.400,50\s€\)/);
    expect(panel).toHaveTextContent('V-2 · Ben Berg · 900,50');
    fireEvent.click(screen.getByRole('button', { name: 'Als eingegangen übernehmen' }));
    expect(takeOverLegacy).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Ja, übernehmen' }));
    await waitFor(() => expect(takeOverLegacy).toHaveBeenCalledWith(['d-1', 'd-2']));
    expect(await screen.findByText('2 Kautionen übernommen.')).toBeInTheDocument();
    await waitFor(() => expect(files.mock.calls.length).toBeGreaterThan(1));
  });

  it('starts an agreement from a chosen contract', async () => {
    const files = vi.fn(async () => ({ items: [], total: 0, totals: { count: 0, amount: 0, received: 0, retention: 0 }, stages: {} }));
    render(<MemoryRouter><Deposits service={{ files }} /></MemoryRouter>);
    await screen.findByText('0 Kautionen');
    fireEvent.change(screen.getByLabelText('Vertrag'), { target: { value: 'c-1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Kaution vereinbaren' }));
    expect(screen.getByRole('dialog', { name: 'Vertrag' })).toHaveTextContent('Vertrag c-1');
  });
});
