import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const authState = vi.hoisted(() => ({ user: null, write: null }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => authState }));
vi.mock('../components/PdfPreview', () => ({ default: () => <div data-testid="pdf" /> }));
const apiMock = vi.hoisted(() => ({
  get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), postBlob: vi.fn(), getBlob: vi.fn(), list: vi.fn(),
}));
vi.mock('../api', () => ({ api: apiMock }));

import DepositFile from '../features/deposits/DepositFile';
import DepositsDialog from '../features/deposits/DepositsDialog';
import { depositService } from '../features/deposits/depositApi';
import { COPY } from '../features/deposits/depositText';

const HASH = 'a'.repeat(64);
const source = {
  contract: { id: 'c-1', contract_number: 'V-1', start_date: '2024-01-01', end_date: '2026-06-30' },
  tenant: { id: 't-1', full_name: 'Mia Muster' }, property: { name: 'Bautzner Straße 61' }, unit: { label: 'WE 3' },
};

function draftSettlement(overrides = {}) {
  return {
    id: 's-1', kind: 'final', settlement_date: '2026-06-30', revision: 'rev-s1', finalized: false, items: [],
    interest_amount: null, interest_reason: null, notes: null, interest: { computed: 12.5, years: [] },
    outcome: { principal: '1500.00', interest: '12.50', credit: '1512.50', new_claims: '0.00', offsets: '0.00',
      retention: '0.00', claims: '0.00', result: '1512.50', payout: '1512.50', remaining_claim: '0.00', covered: '0.00' },
    problems: [{ code: 'defect_open', message: 'Mangel „Bohrlöcher“ ist dem Mieter zugeordnet, aber nicht abgerechnet.', blocking: false }],
    suggestions: {
      defects: [{ id: 'def-1', room: 'Küche', description: 'Bohrlöcher', included: false }],
      receivables: [{ id: 'r-1', due_date: '2026-03-01', amount_due: 120.5, open: 120.5, description: 'Nachzahlung NK 2025', included: false }],
      rent_arrears: 700, retention_allowed: true, monthly_advances: 200,
    },
    ...overrides,
  };
}

function fileFixture(overrides = {}) {
  return {
    deposit: { id: 'd-1', contract_id: 'c-1', amount: 1500, form: 'transfer', account_id: 'acc-1', revision: 'rev-1',
      cap_reason: null, institution: 'Sparkasse', account_reference: 'DE00', account_holder: null, notes: null },
    stage: 'received', settled: false, money_form: true, source,
    cap: { cold_rent: 500, cap: 1500, exceeds: false, excess: 0, known: true },
    account: { id: 'acc-1', name: 'Kautionskonto' }, accounts: [{ id: 'acc-1', name: 'Kautionskonto' }],
    instalments: [{ number: 1, due_date: '2024-01-01', amount: 1500, paid: 1500, open: 0, status: 'paid' }],
    received: 1500, outstanding: 0, surplus: 0,
    payments: [{ id: 'p-1', booking_id: 'b-1', kind: 'receipt', amount: 1500,
      booking: { id: 'b-1', booking_date: '2024-01-01', amount: 1500, payment_text: 'Kaution' } }],
    interest_rates: [], interest: { until: '2026-10-11', total: 0, years: [], balance: 1500 }, retention: 0,
    settlements: [],
    ...overrides,
  };
}

function service(file = fileFixture()) {
  return {
    load: vi.fn(async () => file),
    source: vi.fn(async () => ({ source, cap: file.cap, accounts: file.accounts, suggested_amount: 1500,
      deposits: [{ id: 'd-1', amount: 1500, form: 'transfer', received: 1500, stage: 'received' }] })),
    create: vi.fn(async () => file),
    candidates: vi.fn(async () => ({ items: [{ booking_id: 'b-2', booking_date: '2024-02-03', amount: 1200, free: 1200,
      payment_text: 'Miete und Kaution' }] })),
    addPayment: vi.fn(async () => file),
    startSettlement: vi.fn(async () => fileFixture({ settlements: [draftSettlement()] })),
    saveSettlement: vi.fn(async (id, settlementId, payload) => fileFixture({ settlements: [draftSettlement({
      revision: 'rev-s2', items: payload.items })] })),
    preview: vi.fn(async () => ({ review_hash: HASH, pdf_sha256: HASH, ready: true, problems: [],
      outcome: { ...draftSettlement().outcome, claims: '80.00', result: '1432.50', payout: '1432.50' } })),
    previewPdfUrl: vi.fn(async () => 'blob:preview'),
    finalize: vi.fn(),
    updateAgreement: vi.fn(async () => file),
    setRates: vi.fn(async () => file),
  };
}

describe('deposit texts', () => {
  it('have the same keys in German, English and Spanish', () => {
    const keys = Object.keys(COPY['de-DE']).sort();
    expect(Object.keys(COPY['en-US']).sort()).toEqual(keys);
    expect(Object.keys(COPY['es-ES']).sort()).toEqual(keys);
  });
});

describe('deposit API', () => {
  beforeEach(() => Object.values(apiMock).forEach(fn => fn.mockReset()));

  it('names the endpoints and sends the exact finalize command', async () => {
    apiMock.get.mockResolvedValue({ items: [], total: 0 });
    await depositService.files({ contractId: 'c 1', stage: 'retained', query: 'Mia', skip: 50, limit: 50 });
    expect(apiMock.get).toHaveBeenCalledWith('/deposits/files?skip=50&limit=50&contract_id=c+1&stage=retained&q=Mia',
      expect.anything());
    apiMock.post.mockResolvedValue(fileFixture());
    await depositService.finalize('d-1', 's-1', { idempotencyKey: 'deposit:k1', reviewHash: HASH, payoutAccountId: 'acc-1' });
    expect(apiMock.post).toHaveBeenCalledWith('/deposits/d-1/settlements/s-1/finalize', {
      idempotency_key: 'deposit:k1', review_hash: HASH, confirmed: true, payout_account_id: 'acc-1' }, expect.anything());
    await expect(depositService.finalize('d-1', 's-1', { idempotencyKey: 'x', reviewHash: 'bad' })).rejects.toThrow();
    apiMock.post.mockResolvedValue({ broken: true });
    await expect(depositService.addPayment('d-1', 'b-1')).rejects.toThrow('invalid_deposit_file');
  });
});

describe('DepositsDialog', () => {
  beforeEach(() => { authState.user = { id: 'u-1', role: 'buchhaltung' }; authState.write = null; });

  it('lists the deposits of the contract and agrees a new one within the cap only with a reason', async () => {
    const api = service();
    render(<DepositsDialog contractId="c-1" service={api} onClose={vi.fn()} />);
    expect(await screen.findByText('V-1 · Mia Muster · WE 3')).toBeInTheDocument();
    expect(screen.getByText(/Eingegangen · Eingegangen/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Kaution vereinbaren' }));
    const form = screen.getByRole('form', { name: 'Kaution vereinbaren' });
    fireEvent.change(within(form).getByLabelText('Betrag'), { target: { value: '1600' } });
    expect(within(form).getByRole('alert')).toHaveTextContent('übersteigt drei Nettokaltmieten');
    const save = within(form).getByRole('button', { name: 'Speichern' });
    expect(save).toBeDisabled();
    fireEvent.change(within(form).getByLabelText('Begründung für den höheren Betrag'), { target: { value: 'Einbauküche' } });
    fireEvent.change(within(form).getByLabelText('Raten'), { target: { value: '3' } });
    fireEvent.click(save);
    await waitFor(() => expect(api.create).toHaveBeenCalledWith(expect.objectContaining({
      contract_id: 'c-1', amount: 1600, form: 'transfer', instalment_count: 3, instalment_amounts: [533.34, 533.33, 533.33],
      cap_reason: 'Einbauküche', account_id: null })));
  });
});

describe('DepositFile', () => {
  beforeEach(() => { authState.user = { id: 'u-1', role: 'buchhaltung' }; authState.write = null; });

  it('shows figures, instalments and assigns a payment share', async () => {
    const api = service();
    render(<DepositFile depositId="d-1" service={api} onClose={vi.fn()} />);
    expect(await screen.findByRole('heading', { name: 'Kautionsakte · V-1' })).toBeInTheDocument();
    expect(screen.getByText('bezahlt')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Zahlung zuordnen' }));
    const list = await screen.findByRole('list', { name: 'Buchungen des Mieters' });
    fireEvent.change(within(list).getByLabelText('Anteil (leer = frei)'), { target: { value: '500' } });
    fireEvent.click(within(list).getByRole('button', { name: 'Zuordnen' }));
    await waitFor(() => expect(api.addPayment).toHaveBeenCalledWith('d-1', 'b-2', '500'));
  });

  it('drafts the settlement from suggestions, checks it and repeats a lost finalization exactly', async () => {
    const api = service(fileFixture({ settlements: [draftSettlement()] }));
    const lost = Object.assign(new Error('Netzwerkfehler'), { isNetwork: true });
    api.finalize.mockRejectedValueOnce(lost).mockResolvedValueOnce(fileFixture({ stage: 'settled', settled: true,
      settlements: [draftSettlement({ finalized: true, outcome: { ...draftSettlement().outcome, result: '1432.50' },
        original: { pdf_sha256: HASH, document_id: 'doc-1' } })] }));
    render(<DepositFile depositId="d-1" service={api} onClose={vi.fn()} />);
    const section = await screen.findByRole('region', { name: 'Kautionsabrechnung' });
    fireEvent.click(within(section).getAllByRole('button', { name: 'Übernehmen' })[0]);
    const amounts = within(section).getAllByLabelText('Betrag');
    fireEvent.change(amounts[0], { target: { value: '80' } });
    fireEvent.click(within(section).getByRole('button', { name: 'Prüfen' }));
    await waitFor(() => expect(api.saveSettlement).toHaveBeenCalled());
    const payload = api.saveSettlement.mock.calls[0][2];
    expect(payload.items).toEqual([expect.objectContaining({ kind: 'defect', description: 'Bohrlöcher', amount: 80,
      handover_defect_id: 'def-1', receivable_id: null })]);
    await waitFor(() => expect(api.preview).toHaveBeenCalledWith('d-1', 's-1'));
    const panel = await screen.findByRole('region', { name: 'Kautionsabrechnung' });
    const finalize = within(panel).getByRole('button', { name: 'Abschließen' });
    expect(finalize).toBeDisabled();
    fireEvent.click(within(panel).getByRole('checkbox'));
    fireEvent.click(finalize);
    expect(await within(panel).findByText(/Die Antwort ging verloren/)).toBeInTheDocument();
    fireEvent.click(within(panel).getByRole('button', { name: 'Genau wiederholen' }));
    await waitFor(() => expect(api.finalize).toHaveBeenCalledTimes(2));
    expect(api.finalize.mock.calls[1][2]).toEqual(api.finalize.mock.calls[0][2]);
    expect(api.finalize.mock.calls[0][2]).toEqual(expect.objectContaining({ reviewHash: HASH, payoutAccountId: 'acc-1' }));
    expect(await screen.findByText('Abgeschlossen. Das Original ist archiviert.')).toBeInTheDocument();
  });

  it('is read-only for a role without the deposit area', async () => {
    authState.write = ['/maintenance'];
    render(<DepositFile depositId="d-1" service={service(fileFixture({ settlements: [draftSettlement()] }))} onClose={vi.fn()} />);
    expect(await screen.findByText('Nur Lesezugriff: Ihre Rolle darf Kautionen nicht ändern.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Vereinbarung ändern' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Zahlung zuordnen' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Prüfen' })).toBeNull();
  });
});
