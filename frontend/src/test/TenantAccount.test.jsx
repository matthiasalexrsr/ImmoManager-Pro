import { afterEach, describe, it, expect, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import TenantAccount from '../pages/TenantAccount';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn(), put: vi.fn() } }));
// the form itself is tested on its own; here only what the page gives it and does with the result
vi.mock('../components/FormModal', () => ({ default: ({ title, initial, fields, onSave, onClose }) => <div role="dialog" aria-label={title}>
  <span>{initial.full_name}</span><span>{fields.map(f => f.label).join(', ')}</span>
  <button onClick={async () => { await onSave({ ...initial, phone: '0341 1234' }); onClose(); }}>Speichern</button></div> }));
vi.mock('../components/Toast', () => ({ useToast: () => ({ error: vi.fn() }) }));

const ACCOUNT = {
  contracts: [
    { contract_id: 'w', contract_number: 'MV-Whg', expected: 28120, paid: 13320, outstanding: 14800, overpaid: 0 },
    { contract_id: 'g', contract_number: 'MV-Garage', expected: 1710, paid: 810, outstanding: 900, overpaid: 0 },
  ],
  unassigned: [{ booking_id: 'b', booking_date: '2025-09-20', amount: 2000, unassigned: 430, payment_text: 'Nachzahlung' }],
};
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe('TenantAccount', () => {
  it('shows each contract and the payments without a contract', async () => {
    vi.useFakeTimers({ toFake: ['Date'] }); vi.setSystemTime(new Date(2026, 9, 15, 0, 30));
    api.get.mockImplementation(path => Promise.resolve(path.includes('/account') ? ACCOUNT : { full_name: 'Familie Yilmaz' }));
    render(<MemoryRouter initialEntries={['/tenants/t1/account']}>
      <Routes><Route path="/tenants/:id/account" element={<TenantAccount />} /></Routes>
    </MemoryRouter>);

    expect(await screen.findByText('MV-Garage')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Mieterkonto Familie Yilmaz' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Familie Yilmaz' })).toHaveAttribute('href', '/tenants/t1/account');
    expect(screen.getByRole('link', { name: 'MV-Whg' })).toHaveAttribute('href', '/contracts?contract_id=w');
    expect(screen.getByRole('link', { name: 'MV-Garage' })).toHaveAttribute('href', '/contracts?contract_id=g');
    expect(screen.getByRole('link', { name: 'Nachzahlung' })).toHaveAttribute('href', '/bookings?booking_id=b');
    expect(screen.getByRole('link', { name: 'Buchungen dieses Mieters' })).toHaveAttribute('href', '/bookings?tenant_id=t1');
    expect(screen.getByRole('link', { name: 'Alle Mietverträge' })).toHaveAttribute('href', '/contracts');
    expect(screen.getByText('Nachzahlung')).toBeInTheDocument();
    expect(screen.getByText(/15\.700,00/)).toBeInTheDocument();  // open in total
    expect(screen.getByLabelText('Stichtag')).toHaveValue('2026-10-15');
    fireEvent.click(screen.getByRole('button', { name: /Gezahlt \(zugeordnet\)/ }));
    expect(screen.getByRole('region', { name: 'Vertragsquellen zum Stichtag' })).toHaveFocus();
    fireEvent.click(screen.getByRole('button', { name: /Nicht zugeordnet/ }));
    expect(screen.getByRole('region', { name: 'Nicht zugeordnete Zahlungsquellen zum Stichtag' })).toHaveFocus();
  });

  it('edits the tenant from the account page and shows the facts', async () => {
    const person = { id: 't1', full_name: 'Familie Yilmaz', email: 'yilmaz@example.com', payment_method: 'sepa_direct_debit',
      sepa_mandate: 'M-17', city: 'Leipzig', postal_code: '04109' };
    api.get.mockImplementation(path => Promise.resolve(path.includes('/account') ? ACCOUNT : person));
    api.put.mockResolvedValue({ ...person, phone: '0341 1234' });
    render(<MemoryRouter initialEntries={['/tenants/t1/account']}>
      <Routes><Route path="/tenants/:id/account" element={<TenantAccount />} /></Routes>
    </MemoryRouter>);
    const facts = await screen.findByRole('region', { name: 'Stammdaten' });
    expect(facts).toHaveTextContent('SEPA-Lastschrift');
    expect(facts).toHaveTextContent('M-17');
    expect(facts).toHaveTextContent('04109 Leipzig');
    fireEvent.click(screen.getByRole('button', { name: 'Mieter bearbeiten' }));
    const dialog = screen.getByRole('dialog', { name: 'Mieter bearbeiten' });
    expect(dialog).toHaveTextContent('Familie Yilmaz');
    expect(dialog).toHaveTextContent('Zahlungsart');
    const loads = api.get.mock.calls.length;
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Speichern' })); });
    expect(api.put).toHaveBeenCalledWith('/tenants/t1', expect.objectContaining({ phone: '0341 1234' }));
    expect(api.get.mock.calls.length).toBeGreaterThan(loads);      // the account and the person load again
    expect(screen.queryByRole('dialog', { name: 'Mieter bearbeiten' })).not.toBeInTheDocument();
  });
});
