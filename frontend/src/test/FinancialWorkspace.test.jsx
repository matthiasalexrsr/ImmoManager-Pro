import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  user: null,
  report: vi.fn(),
  sources: vi.fn(),
  exportCsv: vi.fn(),
}));

vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: mocks.user }) }));
vi.mock('../features/financialWorkspace/financialWorkspaceApi', () => ({
  financialWorkspaceApi: {
    report: mocks.report,
    sources: mocks.sources,
    exportCsv: mocks.exportCsv,
  },
}));

const choices = {
  portfolios: [
    { id: 'portfolio-1', name: 'Portfolio A' },
    { id: 'portfolio-2', name: 'Portfolio B' },
  ],
  accounts: [{ id: 'account-1', name: 'Bankkonto A', portfolio_id: 'portfolio-1' }],
  properties: [{ id: 'property-1', name: 'Haus A', portfolio_id: 'portfolio-1' }],
  units: [{ id: 'unit-1', label: 'Wohnung 1', property_id: 'property-1' }],
};

vi.mock('../features/unitInventory/ReferenceChoice', () => ({
  default: ({ kind, label, onChange, filters = {}, value = '' }) => (
    <fieldset data-testid={'ref-' + kind}>
      <legend>{label}</legend>
      <output data-testid={'filters-' + kind}>{JSON.stringify(filters)}</output>
      {choices[kind].map((row, index) => (
        <button type="button" key={row.id} onClick={() => onChange(row.id, row)}>
          {'choose-' + kind + '-' + (index + 1)}
        </button>
      ))}
      {value && <button type="button" onClick={() => onChange('', null)}>{'clear-' + kind}</button>}
    </fieldset>
  ),
}));

import FinancialWorkspace from '../pages/FinancialWorkspace';

const hash = 'd'.repeat(64);
const report = {
  basis: 'confirmed_cash',
  currency: 'EUR',
  filters: {
    date_from: '2026-01-01', date_to: '2026-12-31', portfolio_id: 'portfolio-1',
    property_ids: ['property-1'], unit_id: 'unit-1', account_id: 'account-1',
    basis: 'confirmed_cash', as_of: '2026-12-31',
  },
  source_hash: hash,
  income: '1000.00',
  expense: '250.00',
  net: '750.00',
  source_count: 2,
  excluded_count: 1,
  categories: [],
  months: [],
  locations: [],
};

const sourcePage = {
  ...report,
  items: [{
    id: 'booking-1', booking_date: '2026-01-05', account_id: 'account-1', account_name: 'Bankkonto A',
    category_name: 'Miete', property_name: 'Haus A', unit_label: 'Wohnung 1',
    amount: '1000.00', amount_cents: '100000', status: 'confirmed', included: true,
    exclusion_reason: null, payment_text: 'Miete Januar', receipt_url: null,
  }],
  has_more: false,
  next_after: null,
};

beforeEach(() => {
  mocks.user = {
    id: 'actor-1', role: 'verwalter', is_active: true,
    portfolio_access: 'selected', portfolio_ids: ['portfolio-1'], write_permissions: [],
  };
  mocks.report.mockReset().mockResolvedValue(report);
  mocks.sources.mockReset().mockResolvedValue(sourcePage);
  mocks.exportCsv.mockReset().mockResolvedValue(undefined);
});

async function chooseAndApply() {
  fireEvent.click(screen.getByRole('button', { name: 'choose-portfolios-1' }));
  fireEvent.click(screen.getByRole('button', { name: 'choose-properties-1' }));
  fireEvent.click(screen.getByRole('button', { name: 'choose-accounts-1' }));
  fireEvent.click(screen.getByRole('button', { name: 'choose-units-1' }));
  fireEvent.change(screen.getByLabelText('Zeitraum von'), { target: { value: '2026-01-01' } });
  fireEvent.change(screen.getByLabelText('Zeitraum bis'), { target: { value: '2026-12-31' } });
  fireEvent.change(screen.getByLabelText('Stichtag'), { target: { value: '2026-12-31' } });
  fireEvent.click(screen.getByRole('button', { name: 'Auswertung anwenden' }));
  await waitFor(() => expect(mocks.report).toHaveBeenCalledTimes(1));
}

describe('FinancialWorkspace filter and privacy flow', () => {
  it('keeps draft filters local until apply and binds account/unit choices to parents', async () => {
    render(<FinancialWorkspace />);
    expect(mocks.report).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'choose-portfolios-1' }));
    expect(screen.getByTestId('filters-accounts')).toHaveTextContent('"portfolio_id":"portfolio-1"');
    fireEvent.click(screen.getByRole('button', { name: 'choose-properties-1' }));
    expect(screen.getByTestId('filters-units')).toHaveTextContent('"property_id":"property-1"');
    expect(mocks.report).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'choose-accounts-1' }));
    fireEvent.click(screen.getByRole('button', { name: 'choose-units-1' }));
    fireEvent.change(screen.getByLabelText('Zeitraum von'), { target: { value: '2026-01-01' } });
    fireEvent.change(screen.getByLabelText('Zeitraum bis'), { target: { value: '2026-12-31' } });
    fireEvent.change(screen.getByLabelText('Stichtag'), { target: { value: '2026-12-31' } });
    fireEvent.click(screen.getByRole('button', { name: 'Auswertung anwenden' }));

    await waitFor(() => expect(mocks.report).toHaveBeenCalledWith(expect.objectContaining({
      portfolio_id: 'portfolio-1',
      property_ids: ['property-1'],
      unit_id: 'unit-1',
      account_id: 'account-1',
    }), expect.objectContaining({ signal: expect.any(AbortSignal) })));
    expect(await screen.findByText('1.000,00 €')).toBeInTheDocument();
  });

  it('invalidates child references immediately when the portfolio changes', () => {
    render(<FinancialWorkspace />);
    fireEvent.click(screen.getByRole('button', { name: 'choose-portfolios-1' }));
    fireEvent.click(screen.getByRole('button', { name: 'choose-properties-1' }));
    fireEvent.click(screen.getByRole('button', { name: 'choose-accounts-1' }));
    expect(screen.getByTestId('ref-units')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'choose-portfolios-2' }));
    expect(screen.queryByTestId('ref-units')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'clear-accounts' })).not.toBeInTheDocument();
    expect(screen.getByText('Keine Immobilie ausgewählt')).toBeInTheDocument();
  });

  it('keeps applied filters on source-hash 409 and reloads deliberately', async () => {
    mocks.sources.mockRejectedValueOnce(Object.assign(new Error('changed'), { statusCode: 409 }));
    render(<FinancialWorkspace />);
    await chooseAndApply();

    expect(await screen.findByText('Die Buchungsquellen haben sich geändert.')).toBeInTheDocument();
    expect(screen.getByText(/Portfolio A/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Aktuelle Buchungsquellen neu laden' }));
    await waitFor(() => expect(mocks.report).toHaveBeenCalledTimes(2));
    expect(mocks.report.mock.calls[1][0]).toEqual(mocks.report.mock.calls[0][0]);
  });

  it('removes previous actor report synchronously when identity or grants change', async () => {
    const view = render(<FinancialWorkspace />);
    await chooseAndApply();
    expect(await screen.findByText('1.000,00 €')).toBeInTheDocument();

    mocks.user = {
      id: 'actor-2', role: 'verwalter', is_active: true,
      portfolio_access: 'selected', portfolio_ids: ['portfolio-2'], write_permissions: [],
    };
    view.rerender(<FinancialWorkspace />);

    expect(screen.queryByText('1.000,00 €')).not.toBeInTheDocument();
    expect(screen.queryByText(/Portfolio A/)).not.toBeInTheDocument();
    expect(mocks.report).toHaveBeenCalledTimes(1);
  });
});
