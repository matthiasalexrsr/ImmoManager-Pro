import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import Statements from '../pages/Statements';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }));
const t = (key) => key;
vi.mock('../i18n', () => ({ useTranslation: () => ({ t, locale: 'de-DE' }) }));

const period = { id: 'bp', property_id: 'p', label: 'BK 2025', start_date: '2025-01-01', end_date: '2025-12-31', status: 'draft' };
const DATA = {
  '/billing/periods': [period],
  '/billing/cost-items': [
    { id: 'c1', billing_period_id: 'bp', description: 'Grundsteuer', amount: 1800, allocation_key_id: 'k', is_recoverable: true },
    { id: 'c2', billing_period_id: 'bp', description: 'Dachreparatur', amount: 8000, allocation_key_id: 'k', is_recoverable: false },
  ],
  '/billing/statements': [
    { id: 's1', billing_period_id: 'bp', unit_id: 'u', contract_id: 'k1', party: 'tenant', usage_start: '2025-01-01',
      usage_end: '2025-06-30', usage_days: 181, total_cost: 880.8, advance_paid: 1200, balance: -319.2, status: 'draft' },
    { id: 's2', billing_period_id: 'bp', unit_id: 'u', contract_id: null, party: 'vacancy', usage_start: '2025-07-01',
      usage_end: '2025-08-31', usage_days: 62, total_cost: 301.72, advance_paid: 0, balance: 301.72, status: 'draft' },
  ],
  '/properties': [{ id: 'p', name: 'MFH Leipzig' }],
  '/units': [{ id: 'u', label: 'WE 06' }],
  '/billing/allocation-keys': [{ id: 'k', name: 'Fläche', key_type: 'area_sqm' }],
  '/contracts': [{ id: 'k1', tenant_id: 't1' }],
  '/tenants': [{ id: 't1', full_name: 'Lukas Becker' }],
};

async function openPeriod() {
  render(<Statements />);
  const row = (await screen.findByText('MFH Leipzig')).closest('tr');
  fireEvent.click(within(row).getByLabelText('ui.buttons.edit'));
  return screen.findByText('Lukas Becker');
}

describe('Statements detail', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.get.mockImplementation((path) => Promise.resolve(
      path.endsWith('/preflight') ? { has_blockers: false, blockers: [], warnings: [], metrics: {} } : DATA[path] ?? []));
  });

  it('shows usage periods and the vacancy row without a PDF button', async () => {
    await openPeriod();
    const vacancyRow = screen.getByText('pages.statements.vacancyParty').closest('tr');

    expect(within(vacancyRow).getByText('01.07.2025 – 31.08.2025')).toBeInTheDocument();
    expect(within(vacancyRow).queryByText('PDF')).not.toBeInTheDocument();
    expect(within(vacancyRow).queryByText('301.72 €', { selector: 'span' })).not.toBeInTheDocument();  // no balance
    expect(within(screen.getByText('Lukas Becker').closest('tr')).getByText('PDF')).toBeInTheDocument();
    expect(screen.getByText('pages.statements.notRecoverable')).toBeInTheDocument();
  });

  it('opens the reason dialog for a correction', async () => {
    // Regression: the dialog state was never rendered, so the button did nothing.
    await openPeriod();
    fireEvent.click(screen.getByText('pages.statements.startCorrection'));

    expect(await screen.findByText('pages.statements.revisionReason')).toBeInTheDocument();
  });
});
