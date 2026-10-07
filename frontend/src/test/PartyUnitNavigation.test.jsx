import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import UnitOverview from '../pages/UnitOverview';
import TenantAccount from '../pages/TenantAccount';
import { api } from '../api';

const context = vi.hoisted(() => ({ error: vi.fn(), openParty: vi.fn(), t: () => undefined }));
vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: context.t, locale: 'de-DE' }) }));
vi.mock('../components/Toast', () => ({ useToast: () => ({ error: context.error }) }));
vi.mock('../components/PhotoDropZone', () => ({ default: () => null }));
vi.mock('../features/partyWorkspace/PartyWorkspace', () => ({
  usePartyWorkspace: () => ({ openParty: context.openParty }),
  PartyLink: ({ tenantId, children }) => tenantId
    ? <button type="button" onClick={() => context.openParty(tenantId)}>{children}</button>
    : <span>{children}</span>,
}));

const deferred = () => {
  let resolve;
  const promise = new Promise(yes => { resolve = yes; });
  return { promise, resolve };
};
function UnitRoutes() {
  const navigate = useNavigate();
  return <><button onClick={() => navigate('/units/u2')}>Andere Einheit</button>
    <Routes><Route path="/units/:id" element={<UnitOverview />} /></Routes></>;
}

beforeEach(() => vi.clearAllMocks());
afterEach(() => cleanup());

describe('party navigation in unit and account pages', () => {
  it('does not display the previous unit tenant after navigating while their response is pending', async () => {
    const oldTenant = deferred();
    api.get.mockImplementation(path => {
      if (path === '/tenants/t1') return oldTenant.promise;
      if (path === '/tenants/t2') return Promise.resolve({ id: 't2', full_name: 'Ben Weber' });
      if (path.startsWith('/units/')) return Promise.resolve({ id: path.endsWith('u1') ? 'u1' : 'u2', label: path.endsWith('u1') ? 'Wohnung Alt' : 'Wohnung Neu', status: 'occupied' });
      return Promise.reject(new Error(`Unexpected GET ${path}`));
    });
    api.list.mockImplementation(path => Promise.resolve(path.startsWith('/contracts')
      ? [{ id: path.includes('u1') ? 'c1' : 'c2', unit_id: path.includes('u1') ? 'u1' : 'u2', tenant_id: path.includes('u1') ? 't1' : 't2', contract_number: path.includes('u1') ? 'MV-Alt' : 'MV-Neu', status: 'active', start_date: '2026-01-01' }]
      : []));
    render(<MemoryRouter initialEntries={['/units/u1']}><UnitRoutes /></MemoryRouter>);
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/tenants/t1', expect.anything()));
    fireEvent.click(screen.getByRole('button', { name: 'Andere Einheit' }));
    await screen.findByRole('heading', { name: 'Wohnung Neu' });
    await act(async () => oldTenant.resolve({ id: 't1', full_name: 'Anna Müller' }));
    expect(screen.queryByRole('button', { name: 'Anna Müller' })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Wohnung Alt' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Ben Weber' }));
    expect(context.openParty).toHaveBeenCalledWith('t2');
  });

  it('shows an account loading failure and can retry without presenting an empty account as valid', async () => {
    let unavailable = true;
    const account = { contracts: [{ contract_id: 'c1', contract_number: 'MV-2026', expected: 1000, paid: 800, outstanding: 200, overpaid: 0 }], unassigned: [] };
    api.get.mockImplementation(path => path.includes('/account?')
      ? unavailable ? Promise.reject(new Error('Mieterkonto ist nicht erreichbar')) : Promise.resolve(account)
      : Promise.resolve({ id: 't1', full_name: 'Anna Müller' }));
    render(<MemoryRouter initialEntries={['/tenants/t1/account']}>
      <Routes><Route path="/tenants/:id/account" element={<TenantAccount />} /></Routes>
    </MemoryRouter>);
    expect(await screen.findByRole('alert')).toHaveTextContent('Mieterkonto ist nicht erreichbar');
    expect(screen.queryByRole('heading', { name: /Mieterkonto/ })).not.toBeInTheDocument();
    expect(context.error).toHaveBeenCalledWith('Mieterkonto ist nicht erreichbar');
    unavailable = false;
    fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
    expect(await screen.findByRole('heading', { name: 'Mieterkonto Anna Müller' })).toBeInTheDocument();
    expect(screen.getByText('MV-2026')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
