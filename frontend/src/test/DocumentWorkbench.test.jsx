import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import DocumentWorkbench from '../features/documentWork/DocumentWorkbench';
import InvoiceTakeover from '../features/documentWork/InvoiceTakeover';
import { pageNumbers } from '../features/documentWork/documentWorkApi';

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), current: vi.fn(), canWrite: true }));
vi.mock('../api', () => ({ api: { get: mocks.get, post: mocks.post, captureSession: () => mocks.current } }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => mocks.canWrite }));
vi.mock('../components/PdfPreview', () => ({ default: () => <div>PDF-Originalansicht</div> }));
vi.mock('../features/partyWorkspace/useModalDialog', () => ({ useModalDialog: () => {} }));

const SOURCE = { document: { id: 'd1', title: 'Rechnung Wärme', file_url: '/uploads/documents/rechnung.pdf' },
  filename: 'rechnung.pdf', sha256: 'a'.repeat(64), document_revision: 'b'.repeat(64),
  inspection: { format: 'pdf' }, version: null, annotations: [], layer_revision: 0 };
const close = vi.fn();
beforeEach(() => {
  vi.clearAllMocks(); mocks.canWrite = true;
  mocks.get.mockImplementation(path => Promise.resolve(path.endsWith('/source') ? SOURCE : { items: [], next_after: null }));
});

it('retains the exact archive command after a lost reply and retries with its original key', async () => {
  mocks.post.mockRejectedValueOnce(new Error('Antwort verloren')).mockResolvedValueOnce({ version: { id: 'v1' } });
  render(<DocumentWorkbench documentId="d1" onClose={close} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Original jetzt archivieren' }));
  await screen.findByText('Antwort verloren');
  const first = mocks.post.mock.calls[0];
  expect(first[1]).toMatchObject({ expected_version: null, expected_sha256: 'a'.repeat(64), expected_document_revision: 'b'.repeat(64) });
  expect(first[1].command_key).toMatch(/^[\da-f-]{36}$/);
  fireEvent.click(screen.getByRole('button', { name: 'Denselben Auftrag wiederholen' }));
  await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
  expect(mocks.post.mock.calls[1]).toEqual(first);
});

it('keeps tools read-only without current write permission', async () => {
  mocks.canWrite = false;
  render(<DocumentWorkbench documentId="d1" onClose={close} />);
  expect(await screen.findByRole('button', { name: 'Original jetzt archivieren' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Original jetzt archivieren' }));
  expect(mocks.post).not.toHaveBeenCalled();
});

it('closes its document on session change', async () => {
  render(<DocumentWorkbench documentId="d1" onClose={close} />);
  await screen.findByText('Datei: rechnung.pdf · Noch nicht archiviert');
  act(() => window.dispatchEvent(new CustomEvent('workspace-logout')));
  expect(close).toHaveBeenCalledTimes(1);
});

it('does not expose a source when the captured session rejects a late response', async () => {
  mocks.current.mockImplementationOnce(() => { throw new Error('Sitzung geändert'); });
  render(<DocumentWorkbench documentId="d1" onClose={close} />);
  await screen.findByText('Sitzung geändert');
  expect(screen.queryByText('Rechnung Wärme', { exact: true })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Original jetzt archivieren' })).not.toBeInTheDocument();
});

it('requires reviewed field origins and carries decimal strings plus VAT and Skonto to the existing review receipt', async () => {
  const perform = vi.fn();
  render(<InvoiceTakeover source={SOURCE} proposal={{ proposal_id: 'p1', source_sha256: SOURCE.sha256,
    observed: { supplier: 'OCR-Lieferant', total_amount: '119,00', invoice_number: 'R-1', invoice_date: '2026-10-01' } }}
    perform={perform} disabled={false} base="/documents/d1/work" />);
  expect(screen.getByRole('button', { name: 'Als Rechnungsentwurf übernehmen' })).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Nettobetrag (€)'), { target: { value: '100,00' } });
  fireEvent.change(screen.getByLabelText('Umsatzsteuerbetrag (€)'), { target: { value: '19,00' } });
  fireEvent.change(screen.getByLabelText('Skonto (%)'), { target: { value: '2' } });
  fireEvent.change(screen.getByLabelText('Skontofrist (Tage)'), { target: { value: '10' } });
  for (const select of screen.getAllByLabelText('Herkunft bestätigen')) fireEvent.change(select, { target: { value: 'manual_correction' } });
  fireEvent.click(screen.getByLabelText('Ich habe die Angaben mit dem Original verglichen.'));
  fireEvent.click(screen.getByRole('button', { name: 'Als Rechnungsentwurf übernehmen' }));
  expect(perform).toHaveBeenCalledTimes(1);
  const payload = perform.mock.calls[0][1];
  expect(payload.receipt.invoice).toMatchObject({ net_amount: '100.00', vat_amount: '19.00', gross_amount: '119.00' });
  expect(payload.receipt).toMatchObject({ skonto_percent: '2', skonto_days: 10, vat_lines: [{ rate: '19', net: '100.00', vat: '19.00' }] });
  expect(payload.confirmed).toBe(true);
  expect(Object.keys(payload.field_sources)).toHaveLength(7);
});

describe('human page selection', () => {
  it('preserves explicit ordering, extraction ranges and duplicate pages', () => {
    expect(pageNumbers('3,1-2,3')).toEqual([2, 0, 1, 2]);
  });
  it.each(['0', '2-1', 'NaN', '1;2', '1.5', ''])('refuses ambiguous selection %s', value => {
    expect(() => pageNumbers(value)).toThrow();
  });
});
