import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
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

describe('TenantAccount', () => {
  it('shows each contract and the payments without a contract', async () => {
    api.get.mockImplementation(path => Promise.resolve(path.includes('/account') ? ACCOUNT : { full_name: 'Familie Yilmaz' }));
    render(<MemoryRouter initialEntries={['/tenants/t1/account']}>
      <Routes><Route path="/tenants/:id/account" element={<TenantAccount />} /></Routes>
    </MemoryRouter>);

    expect(await screen.findByText('MV-Garage')).toBeInTheDocument();
    expect(screen.getByText('Mieterkonto Familie Yilmaz')).toBeInTheDocument();
    expect(screen.getByText('Nachzahlung')).toBeInTheDocument();
    expect(screen.getByText(/15\.700,00/)).toBeInTheDocument();  // open in total
  });
});
