import { afterEach, describe, it, expect, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import TenantAccount from '../pages/TenantAccount';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn() } }));
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
});
