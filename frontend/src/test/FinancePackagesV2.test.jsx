import { beforeEach, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import FinanceReports from '../features/FinanceReports';
import ReceivableSettlement from '../features/ReceivableSettlement';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), getBlob: vi.fn(), captureSession: vi.fn() } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'finance-test-owner' } }), useCanWrite: () => true }));
beforeEach(() => {
  vi.resetAllMocks();
  sessionStorage.clear();
  localStorage.clear();
  api.captureSession.mockReturnValue(() => {});
  api.list.mockResolvedValue([]);
});

it('uses the saved scenario unchanged for calculation and export and shows a failed load', async () => {
  const definition = { version: 2, kind: 'liquidity-v2', as_of: '2026-01-15', months: 3,
    rent_payment_day: 3, rent_collection_percent: '80', arrears_collection_percent: '20', vacant_unit_ids: [], planned_flows: [] };
  api.list.mockImplementation(path => Promise.resolve(path.includes('/saved') ? [{ id: 'saved-1', name: 'Ausfall 20 %', definition }] : []));
  api.get.mockResolvedValue({ definition_hash: 'abcdef123456', result_hash: 'checked-result', basis: 'liquidity-v2', opening_balance: '1000', closing_balance: '1160', monthly: [
    { month: '2026-01', income: '0', expense: '0', balance: '1000' },
    { month: '2026-02', income: '80', expense: '0', balance: '1080' },
    { month: '2026-03', income: '80', expense: '0', balance: '1160' }], sources: [], warnings: [] });
  api.getBlob.mockRejectedValue(new Error('Export vorübergehend nicht erreichbar'));
  render(<MemoryRouter><FinanceReports /></MemoryRouter>);
  fireEvent.click(screen.getByRole('button', { name: 'Bericht erstellen oder öffnen' }));
  await screen.findByRole('option', { name: 'Ausfall 20 %' });
  fireEvent.change(screen.getByLabelText('Gespeicherten Bericht öffnen'), { target: { value: 'saved-1' } });
  fireEvent.click(screen.getByRole('button', { name: 'Berechnen' }));
  await screen.findByRole('button', { name: 'Quellen für 2026-03 anzeigen' });
  expect(api.get).toHaveBeenCalledWith(`/reports/v2/preview?definition=${encodeURIComponent(JSON.stringify(definition))}`);
  fireEvent.click(screen.getByRole('button', { name: 'PDF herunterladen' }));
  await screen.findByRole('alert');
  expect(api.getBlob).toHaveBeenCalledWith(`/reports/v2/preview?format=pdf&definition=${encodeURIComponent(JSON.stringify(definition))}&expected_result_hash=checked-result`);
  expect(screen.getByLabelText('Erwarteter Mieteingang (%)')).toHaveValue(80);
  expect(screen.getByRole('alert')).toHaveTextContent('Export vorübergehend nicht erreichbar');
});

it('keeps amount, date and key after a conflict and refreshes only the expected revision', async () => {
  const state = { residual: '60.00', revision: 'revision1', evidence: [], unresolved_legacy: false };
  api.get.mockImplementation(path => Promise.resolve(path.includes('/residual') ? state : { id: 'c1', tenant_id: 't1' }));
  api.list.mockImplementation(path => Promise.resolve(path.startsWith('/bookings') ? [{ id: 'b1', amount: 40, booking_date: '2026-01-02', payment_text: 'Nachzahlung' }] : []));
  api.post.mockRejectedValue(new Error('Die Forderung wurde geändert.'));
  render(<ReceivableSettlement receivable={{ id: 'r1', contract_id: 'c1' }} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Rest / Ausgleich' }));
  await screen.findByRole('option', { name: /Nachzahlung/ });
  fireEvent.change(screen.getByLabelText('Zahlung oder Guthaben'), { target: { value: 'booking:b1' } });
  fireEvent.change(screen.getByLabelText('Teilbetrag (€)'), { target: { value: '40' } });
  fireEvent.change(screen.getByLabelText('Begründung'), { target: { value: 'Beleg geprüft' } });
  fireEvent.click(screen.getByRole('button', { name: 'Belegt zuordnen' }));
  await screen.findByRole('alert');
  expect(screen.getByLabelText('Teilbetrag (€)')).toHaveValue(40);
  const first = api.post.mock.calls[0][1];
  fireEvent.click(screen.getByRole('button', { name: 'Belegt zuordnen' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2));
  expect(api.post.mock.calls[1][1]).toEqual(first);
  expect(first).toMatchObject({ booking_id: 'b1', amount: '40', reason: 'Beleg geprüft', expected_revision: 'revision1' });
});

it('never displays a successful zero report on source failure', async () => {
  api.list.mockRejectedValue(new Error('Berechtigung entzogen'));
  render(<MemoryRouter><FinanceReports /></MemoryRouter>);
  fireEvent.click(screen.getByRole('button', { name: 'Bericht erstellen oder öffnen' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Berechtigung entzogen');
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
});

it('recovers the exact uncertain command after a page crash without using a fresh source revision', async () => {
  api.get.mockResolvedValue({ residual: '60.00', revision: 'before', evidence: [], unresolved_legacy: false });
  api.post.mockRejectedValueOnce(new Error('Verbindung nach dem Speichern verloren')).mockResolvedValue({ id: 'existing-result' });
  const first = render(<ReceivableSettlement receivable={{ id: 'r1', contract_id: 'c1' }} />);
  await screen.findByRole('button', { name: 'Rest / Ausgleich' });
  // Simulate a crash after dispatch: the persisted request is the one that may already have committed.
  const request = { expected_revision: 'before', idempotency_key: 'uncertain-command-001', booking_id: 'b1', amount: '40', effective_date: '2026-01-10', reason: 'Nachzahlung' };
  localStorage.setItem('workspace:finance-test-owner:finance-command:r1', JSON.stringify({ path: '/receivables/r1/settlements', request }));
  first.unmount();
  api.get.mockResolvedValue({ residual: '20.00', revision: 'after', evidence: [], unresolved_legacy: false });
  render(<ReceivableSettlement receivable={{ id: 'r1', contract_id: 'c1' }} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Ausgleich prüfen und fortsetzen' }));
  await screen.findByRole('alert');
  fireEvent.click(screen.getByRole('button', { name: 'Ausgleich prüfen und fortsetzen' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2));
  expect(api.post.mock.calls[0][1]).toEqual(request);
  expect(api.post.mock.calls[1][1]).toEqual(request);
  await waitFor(() => expect(localStorage.getItem('workspace:finance-test-owner:finance-command:r1')).toBeNull());
});
