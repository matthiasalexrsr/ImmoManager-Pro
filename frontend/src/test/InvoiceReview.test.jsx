import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import InvoiceReview from '../pages/InvoiceReview';
import InvoiceReviewDetail from '../pages/InvoiceReviewDetail';
import { api } from '../api';
import { de, en, es } from '../features/invoiceReview/text';
import { findingText } from '../features/invoiceReview/reviewApi';

vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(),
  upload: vi.fn() } }));
const lang = vi.hoisted(() => ({ locale: 'de-DE' }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key, locale: lang.locale }) }));
const access = vi.hoisted(() => ({ canWrite: true }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => access.canWrite }));
vi.mock('../components/PdfPreview', () => ({ default: ({ url }) => <div data-testid="pdf">{url}</div> }));
vi.mock('../components/FileViewer', () => ({ default: () => <div data-testid="viewer" /> }));

const SETTLED = { gross: 1190, status: 'received', payable: null, approved: null, credits: 0, disputed: 0, dispute_open: 0,
  dispute_settled: 0, written_off: 0, paid: 0, skonto_amount: 0, skonto_until: null, skonto_taken: 0,
  skonto_available: false, due_on: '2026-11-01', open: 0, payment_status: 'not_payable', overdue: false,
  flow_amount: 1190, findings: [] };
const ROW = { invoice_id: 'i1', supplier: 'Dach Müller GmbH', invoice_number: 'RE-1', invoice_date: '2026-10-01',
  property_id: 'p1', property_name: 'Nordhaus', gross_amount: 1190, status: 'received', kind: 'invoice',
  dispute_status: null, settlement: SETTLED };
const ABILITIES = { receive: false, edit_receipt: true, factual_check: true, arithmetic_check: true, decide: true,
  decide_above_limit: true, resolve_dispute: false, transfer_cost: false, pay: true, settings: true };
const VIEW = {
  invoice: { id: 'i1', supplier: 'Dach Müller GmbH', invoice_number: 'RE-1', invoice_date: '2026-10-01', net_amount: 1000,
    vat_amount: 190, gross_amount: 1190, property_id: 'p1', source_document_id: 'd1' },
  review: { id: 'r1', invoice_id: 'i1', kind: 'invoice', status: 'received', received_on: '2026-10-02', checklist: {},
    factual_result: 'confirmed', factual_by_name: 'Anna', arithmetic_result: null, dispute_status: null },
  status: 'received', kind: 'invoice',
  document: { id: 'd1', title: 'Rechnung RE-1', file_url: '/uploads/documents/re1.pdf', integrity: 'unchanged' },
  assignment: { kind: 'maintenance_order', case_id: 'c1', order: { order_number: 'A-7' } },
  arithmetic: { lines: [{ rate: 19, net: 1000, vat: 190 }], findings: [] },
  checklist: { small_invoice: false, missing: ['tax_number'], complete: false, items: [
    { key: 'issue_date', label: 'Ausstellungsdatum', required: true, present: true, source: 'auto' },
    { key: 'tax_number', label: 'Steuernummer', required: true, present: null, source: 'manual' }] },
  factual_findings: [], duplicates: [],
  findings: [{ code: 'over_order', severity: 'warning', message: 'Über Auftrag', params: { difference: 167, ordered: 1309,
    billed: 1476, billed_elsewhere: 1000 } }],
  settlement: SETTLED, payments: [], credit_notes: [], credit_for: null, transfer: null,
  history: [{ id: 'e1', seq: 1, action: 'received', amount: 1190, reason: null, actor_name: 'Bert',
    created_at: '2026-10-02T08:00:00Z' }],
  four_eyes: { limit: 1000, required: true }, settings: { four_eyes_limit: 1000 }, abilities: ABILITIES,
};

function showInbox() {
  api.list.mockResolvedValue([{ id: 'p1', name: 'Nordhaus' }]);
  api.get.mockImplementation(path => {
    if (path.startsWith('/invoice-review/inbox')) return Promise.resolve({ items: [ROW], total: 51, skip: 0, limit: 50, has_more: true });
    if (path.startsWith('/invoice-review/payment-proposals')) return Promise.resolve({ items: [{ invoice_id: 'i2',
      supplier: 'Glanz GmbH', payment_reference: 'G-7', pay_by: '2026-10-15', proposed_amount: 116.62, skonto_amount: 2.38,
      skonto_until: '2026-10-15', overdue: false, dispute_open: 0 }], total: 1, total_amount: 116.62 });
    return Promise.reject(new Error(`unexpected ${path}`));
  });
  return render(<MemoryRouter><InvoiceReview /></MemoryRouter>);
}

function showDetail(view = VIEW) {
  api.get.mockImplementation(path => (path === '/invoices/i1/review' ? Promise.resolve(view)
    : Promise.reject(new Error(`unexpected ${path}`))));
  api.list.mockResolvedValue([]);
  return render(<MemoryRouter initialEntries={['/invoice-review/i1']}>
    <Routes><Route path="/invoice-review/:id" element={<InvoiceReviewDetail />} /></Routes></MemoryRouter>);
}

beforeEach(() => {
  vi.clearAllMocks();
  lang.locale = 'de-DE';
  access.canWrite = true;
});

describe('invoice review inbox', () => {
  it('lists invoices with review and payment state and filters on the server', async () => {
    showInbox();
    expect(await screen.findByText('Dach Müller GmbH')).toBeInTheDocument();
    expect(screen.getByText('1–1 von 51')).toBeInTheDocument();
    const list = screen.getByRole('list');
    expect(within(list).getByText('Eingang erfasst')).toBeInTheDocument();
    expect(within(list).getByText('noch nicht freigegeben')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'pending' } });
    fireEvent.click(screen.getByLabelText('Nur mit offener Skontofrist'));
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith(
      '/invoice-review/inbox?status=pending&skonto=true&skip=0&limit=50', expect.anything()));
    fireEvent.click(screen.getByRole('button', { name: 'Weiter' }));
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith(
      '/invoice-review/inbox?status=pending&skonto=true&skip=50&limit=50', expect.anything()));
  });

  it('shows payment proposals without any bank action', async () => {
    showInbox();
    fireEvent.click(await screen.findByRole('tab', { name: 'Zahlungsvorschläge' }));
    expect(await screen.findByText(/es wird keine Zahlungsdatei erzeugt/)).toBeInTheDocument();
    expect(screen.getByText('Glanz GmbH')).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });
});

describe('invoice review view', () => {
  it('shows the document beside checklist, findings, four-eyes hint and history', async () => {
    showDetail();
    expect(await screen.findByTestId('pdf')).toHaveTextContent('/uploads/documents/re1.pdf');
    expect(screen.getByText('Beleg unverändert seit Eingang')).toBeInTheDocument();
    expect(screen.getByText(/Über Auftrag um 167,00/)).toBeInTheDocument();
    expect(screen.getByText(/Vier-Augen-Prinzip/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Steuernummer/)).not.toBeDisabled();
    expect(screen.getByLabelText(/Ausstellungsdatum/)).toBeDisabled();
    const history = screen.getByRole('region', { name: 'Prüfverlauf' });
    expect(within(history).getByText('Eingang erfasst')).toBeInTheDocument();
    expect(within(history).getByText(/Bert/)).toBeInTheDocument();
  });

  it('sends the arithmetic check with the checklist and requires a reason to reject', async () => {
    api.post.mockResolvedValue({});
    showDetail();
    fireEvent.click(await screen.findByLabelText(/Steuernummer/));
    const arithmetic = screen.getByRole('region', { name: 'Rechnerische Prüfung' });
    fireEvent.click(within(arithmetic).getByRole('button', { name: 'Bestätigen' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/invoices/i1/review/arithmetic-check',
      { result: 'confirmed', checklist: { tax_number: true } }));
    const decision = screen.getByRole('region', { name: 'Entscheidung' });
    expect(within(decision).getByRole('button', { name: 'Ablehnen' })).toBeDisabled();
    fireEvent.change(within(decision).getByLabelText('Begründung'), { target: { value: 'Leistung fehlt' } });
    fireEvent.click(within(decision).getByRole('button', { name: 'Ablehnen' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/invoices/i1/review/decision',
      { decision: 'reject', reason: 'Leistung fehlt' }));
  });

  it('offers the receipt for a legacy invoice and nothing to a read-only role', async () => {
    api.post.mockResolvedValue({});
    const legacy = { ...VIEW, review: null, status: 'legacy', history: [], findings: [],
      abilities: { ...Object.fromEntries(Object.keys(ABILITIES).map(k => [k, false])), receive: true } };
    const first = showDetail(legacy);
    expect(await screen.findByText(/noch nicht geprüft \(Bestand\)/)).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole('button', { name: 'Eingang erfassen' }).at(-1));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/invoices/i1/review',
      expect.objectContaining({ kind: 'invoice', document_id: 'd1', recoverable: false })));
    first.unmount();
    showDetail({ ...VIEW, abilities: Object.fromEntries(Object.keys(ABILITIES).map(k => [k, false])) });
    expect(await screen.findByText(/Nur Lesen/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Freigeben' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Bestätigen' })).toBeNull();
  });

  it('speaks English and Spanish with the same texts', async () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(de).sort());
    expect(Object.keys(es).sort()).toEqual(Object.keys(de).sort());
    expect(findingText(en, VIEW.findings[0])).toMatch(/^Over the order by/);
    expect(findingText(de, { code: 'unknown', message: 'Server sagt' })).toBe('Server sagt');
    lang.locale = 'es-ES';
    showDetail();
    expect(await screen.findByText('Historial de revisión')).toBeInTheDocument();
  });
});
