import { beforeEach, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import Invoices from '../pages/Invoices';
import de from '../../../i18n/de-DE.json';
const mocks = vi.hoisted(() => ({ role: 'buchhaltung', data: null, get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), reload: vi.fn(), confirm: vi.fn() }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../hooks/useFinanceData', () => ({ useFinanceData: () => ({ data: mocks.data, loading: false, error: null, reload: mocks.reload }) }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'synthetic-user', role: mocks.role } }) }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => ({ invalidateRelated: vi.fn() }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => mocks.confirm }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: 'de-DE', t: key => key.split('.').reduce((value, part) => value?.[part], de) || key }) }));
vi.mock('../components/DataTable', () => ({ default: ({ data, columns, onAdd, onEdit }) => <div>
  {onAdd && <button onClick={onAdd}>Create invoice</button>}
  {data.map(row => <div key={row.id} data-testid={row.id}>{columns.map(column => <span key={column.key}>
    {column.render ? column.render(row[column.key], row) : String(row[column.key] ?? '')}</span>)}
    {onEdit && <button onClick={() => onEdit(row)}>Edit invoice</button>}</div>)}
</div> }));
const invoice = { id: 'invoice-1', supplier: 'Synthetic supplier', property_id: 'property', invoice_date: '2026-09-01',
  invoice_number: 'INV-AX', status: 'partial', amount_paid: '40.10', gross_amount: '100.30', net_amount: '100.30', vat_rate: 0, vat_amount: 0 };
beforeEach(() => {
  vi.clearAllMocks(); mocks.role = 'buchhaltung'; mocks.data = { invoices: [invoice], properties: [{ id: 'property', name: 'Synthetic property' }], taxRates: [] };
  mocks.get.mockResolvedValue({ items: [], has_more: false, next_cursor: null });
});
it('shows the central receipt balance and links to actual bank review without offering a paid-status shortcut', () => {
  render(<Invoices />);
  const row = screen.getByTestId('invoice-1');
  expect(row).toHaveTextContent('40,10 €'); expect(row).toHaveTextContent('60,20 €');
  expect(within(row).getByRole('link', { name: de.bankMatching.invoiceNavigation })).toHaveAttribute('href', '/bookings?invoice_id=invoice-1');
  expect(screen.queryByRole('button', { name: /✓ Bezahlt/ })).not.toBeInTheDocument();
  expect(mocks.patch).not.toHaveBeenCalled(); expect(mocks.post).not.toHaveBeenCalled();
});
it('retains readonly access to paged invoice receipts and hides mutation controls', async () => {
  mocks.role = 'readonly'; render(<Invoices />);
  fireEvent.click(screen.getByRole('button', { name: de.bankMatching.history }));
  await screen.findByText(de.bankMatching.noHistory);
  expect(mocks.get).toHaveBeenCalledWith('/invoices/invoice-1/payments?page_size=25', expect.objectContaining({ signal: expect.any(AbortSignal) }));
  expect(screen.queryByRole('button', { name: 'Edit invoice' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Create invoice' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: de.bankMatching.reverse })).not.toBeInTheDocument();
});
it('keeps receipted status read-only while allowing ordinary invoice metadata edits', () => {
  render(<Invoices />); fireEvent.click(screen.getByRole('button', { name: 'Edit invoice' }));
  const dialog = screen.getByRole('dialog');
  expect(within(dialog).getByLabelText('Status')).toBeDisabled();
  expect(within(dialog).getByLabelText('Status')).toHaveValue('partial');
  expect(within(dialog).getByLabelText('Lieferant', { exact: false })).toBeEnabled();
});
it('does not invent a payment when creating a new invoice', () => {
  render(<Invoices />); fireEvent.click(screen.getByRole('button', { name: 'Create invoice' }));
  const dialog = screen.getByRole('dialog');
  const status = within(dialog).getByLabelText('Status');
  expect(within(status).queryByRole('option', { name: 'Bezahlt', exact: true })).not.toBeInTheDocument();
  expect(within(status).queryByRole('option', { name: 'Teilweise bezahlt', exact: true })).not.toBeInTheDocument();
  expect(status).toHaveValue('open'); expect(mocks.post).not.toHaveBeenCalled();
});
it('keeps a carried-over paid balance visible while showing that no payment receipts are stored', async () => {
  mocks.data.invoices = [{ ...invoice, status: 'paid', amount_paid: '100.30' }];
  render(<Invoices />);
  expect(screen.getByText(de.bankMatching.invoiceBalanceHelp)).toBeInTheDocument();
  expect(screen.getByTestId('invoice-1')).toHaveTextContent('100,30 €');
  fireEvent.click(screen.getByRole('button', { name: de.bankMatching.history }));
  await screen.findByText(de.bankMatching.noHistory);
  expect(mocks.post).not.toHaveBeenCalled();
  expect(mocks.patch).not.toHaveBeenCalled();
  expect(screen.queryByRole('button', { name: de.bankMatching.reverse })).not.toBeInTheDocument();
});
