import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { useState } from 'react';

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
    apiMock.put.mockResolvedValue(fileFixture());
    await depositService.setTakeover('d-1', { base_revision: 'rev-1', carried_on: '2024-01-01', carried_amount: 1500 });
    expect(apiMock.put).toHaveBeenCalledWith('/deposits/d-1/takeover',
      { base_revision: 'rev-1', carried_on: '2024-01-01', carried_amount: 1500 }, expect.anything());
    apiMock.post.mockResolvedValue({ taken_over: 2 });
    await depositService.takeOverLegacy(['d-1', 'd-2']);
    expect(apiMock.post).toHaveBeenLastCalledWith('/deposits/legacy-takeover', { deposit_ids: ['d-1', 'd-2'] }, expect.anything());
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

  it('takes over a deposit paid before the app, prefilled from the earlier record', async () => {
    const legacy = fileFixture({ deposit: { ...fileFixture().deposit, held_date: '2024-01-01' }, legacy_candidate: true,
      stage: 'agreed', received: 0, outstanding: 1500, payments: [] });
    const taken = fileFixture({ deposit: { ...fileFixture().deposit, revision: 'rev-2', carried_on: '2024-01-01', carried_amount: 1500,
      carried_interest: 15, carried_note: 'Kontoauszug 31.12.2024' }, payments: [],
      interest: { until: '2026-10-11', total: 40.2, carried: 15, years: [], balance: 1540.2 } });
    const api = { ...service(legacy), setTakeover: vi.fn(async () => taken) };
    render(<DepositFile depositId="d-1" service={api} onClose={vi.fn()} />);
    const section = await screen.findByRole('region', { name: 'Übernahme aus dem Vorsystem' });
    fireEvent.click(within(section).getByRole('button', { name: 'Übernahme erfassen' }));
    expect(within(section).getByText(/als gehalten seit 01.01.2024 erfasst/)).toBeInTheDocument();
    expect(within(section).getByLabelText('Übernahmetag')).toHaveValue('2024-01-01');
    expect(within(section).getByLabelText('Bis dahin eingegangen')).toHaveValue(1500);
    fireEvent.change(within(section).getByLabelText('Bis dahin gutgeschriebene Zinsen'), { target: { value: '15' } });
    fireEvent.change(within(section).getByLabelText('Nachweis / Vermerk (z. B. Kontoauszug)'), { target: { value: ' Kontoauszug 31.12.2024 ' } });
    fireEvent.click(within(section).getByRole('button', { name: 'Übernahme speichern' }));
    await waitFor(() => expect(api.setTakeover).toHaveBeenCalledWith('d-1', { base_revision: 'rev-1', carried_on: '2024-01-01',
      carried_amount: 1500, carried_interest: 15, carried_note: 'Kontoauszug 31.12.2024' }));
    const after = await screen.findByRole('region', { name: 'Übernahme aus dem Vorsystem' });
    expect(within(after).getByText(/Übernommen zum 01.01.2024: 1\.500,00\s€ eingegangen/)).toBeInTheDocument();
    expect(screen.getByText(/davon bis zur Übernahme gutgeschrieben: 15,00\s€/)).toBeInTheDocument();
    fireEvent.click(within(after).getByRole('button', { name: 'Übernahme ändern' }));
    fireEvent.click(within(after).getByRole('button', { name: 'Übernahme entfernen' }));
    await waitFor(() => expect(api.setTakeover).toHaveBeenLastCalledWith('d-1', { base_revision: 'rev-2', carried_on: null,
      carried_amount: null, carried_interest: null, carried_note: null }));
  });

  it('is read-only for a role without the deposit area', async () => {
    authState.write = ['/maintenance'];
    render(<DepositFile depositId="d-1" service={service(fileFixture({ settlements: [draftSettlement()] }))} onClose={vi.fn()} />);
    expect(await screen.findByText('Nur Lesezugriff: Ihre Rolle darf Kautionen nicht ändern.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Vereinbarung ändern' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Zahlung zuordnen' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Prüfen' })).toBeNull();
    expect(screen.queryByRole('region', { name: 'Übernahme aus dem Vorsystem' })).toBeNull();
  });
});

describe('deposit file record navigation', () => {
  beforeEach(() => { authState.user = { id: 'u-1', role: 'readonly' }; authState.write = []; });

  it('offers exact contract, tenant-account, deposit-account and booking links in a routed dialog', async () => {
    const file = fileFixture();
    file.payments[0].booking = { ...file.payments[0].booking, id: 'b ?/1' };
    const testService = service(file);
    render(<MemoryRouter initialEntries={['/deposits?deposit_id=d-1']}><Routes>
      <Route path="/deposits" element={<DepositFile depositId="d-1" service={testService} onClose={vi.fn()} />} />
      <Route path="/bookings" element={<h1>Buchungsübersicht</h1>} />
    </Routes></MemoryRouter>);
    const dialog = await screen.findByRole('dialog', { name: /Kautionsakte/ });
    const related = within(dialog).getByRole('navigation', { name: 'Verknüpfte Seiten' });
    expect(within(related).getByRole('link', { name: 'Mietvertrag öffnen' }))
      .toHaveAttribute('href', '/contracts?contract_id=c-1');
    expect(within(related).getByRole('link', { name: 'Mieterkonto öffnen' }))
      .toHaveAttribute('href', '/tenants/t-1/account');
    expect(within(related).getByRole('link', { name: 'Buchungen des Kautionskontos' }))
      .toHaveAttribute('href', '/bookings?konto=acc-1');
    const paymentLink = within(dialog).getByRole('link', { name: 'Kaution' });
    expect(paymentLink).toHaveAttribute('href', '/bookings?booking_id=b%20%3F%2F1');
    expect(within(dialog).getByRole('note')).toHaveTextContent('Nur Lesezugriff');
    expect(within(dialog).queryByRole('button', { name: 'Zahlung zuordnen' })).not.toBeInTheDocument();
    fireEvent.click(paymentLink);
    expect(await screen.findByRole('heading', { name: 'Buchungsübersicht' })).toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: /Kautionsakte/ })).not.toBeInTheDocument();
    expect(testService.addPayment).not.toHaveBeenCalled();
  });

  it('does not invent links for absent tenant, account and booking IDs', async () => {
    const base = fileFixture();
    const noRelations = fileFixture({
      deposit: { ...base.deposit, account_id: null },
      source: { ...source, tenant: { full_name: 'Mia Muster' } },
      account: null,
      payments: [{ id: 'p-1', booking_id: null, kind: 'receipt', amount: 1500,
        booking: { booking_date: '2024-01-01', payment_text: 'Manuell', amount: 1500 } }],
    });
    render(<MemoryRouter><DepositFile depositId="d-1" service={service(noRelations)} onClose={vi.fn()} /></MemoryRouter>);
    const dialog = await screen.findByRole('dialog', { name: /Kautionsakte/ });
    const related = within(dialog).getByRole('navigation', { name: 'Verknüpfte Seiten' });
    expect(within(related).getAllByRole('link')).toHaveLength(1);
    expect(within(related).getByRole('link', { name: 'Mietvertrag öffnen' }))
      .toHaveAttribute('href', '/contracts?contract_id=c-1');
    expect(within(dialog).getByText('Manuell')).toBeInTheDocument();
    expect(within(dialog).queryByRole('link', { name: 'Manuell' })).not.toBeInTheDocument();
  });
});

function GuardRoute() {
  const where = useLocation();
  return <span data-testid="guard-route">{where.pathname + where.search}</span>;
}
function GuardHarness({ file = fileFixture(), serviceOverride = null }) {
  const [visible, setVisible] = useState(true);
  const sourceService = useState(() => serviceOverride || service(file))[0];
  return <MemoryRouter initialEntries={['/deposits?deposit_id=d-1&source=contract']}>
    <GuardRoute />
    <Routes>
      <Route path="/deposits" element={visible
        ? <DepositFile depositId="d-1" service={sourceService} onClose={() => setVisible(false)} />
        : <p>Deposit file closed</p>} />
      <Route path="/contracts" element={<h1>Contract navigation reached</h1>} />
      <Route path="/bookings" element={<h1>Booking navigation reached</h1>} />
      <Route path="/tenants/:id/account" element={<h1>Tenant navigation reached</h1>} />
    </Routes>
  </MemoryRouter>;
}
const linkedContract = () => screen.getByRole('link', { name: 'Mietvertrag öffnen' });

describe('guard unsaved deposit file navigation', () => {
  beforeEach(() => { authState.user = { id: 'u-1', role: 'buchhaltung' }; authState.write = null; });

  it('keeps an edited agreement on first link click, Escape and cancel; follows only after explicit confirmation', async () => {
    const testService = service();
    render(<GuardHarness serviceOverride={testService} />);
    const dialog = await screen.findByRole('dialog', { name: /Kautionsakte/ });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Vereinbarung ändern' }));
    const form = within(dialog).getByRole('form', { name: 'Vereinbarung ändern' });
    const notes = within(form).getByRole('textbox', { name: 'Notizen' });
    fireEvent.change(notes, { target: { value: 'Noch zu prüfen' } });
    fireEvent.click(linkedContract());
    expect(screen.getByTestId('guard-route')).toHaveTextContent('/deposits?deposit_id=d-1');
    const confirmation = within(dialog).getByRole('group', { name: 'Ungespeicherte Kautionsänderungen' });
    expect(confirmation).toHaveTextContent('Ungespeicherte Änderungen gehen beim Verlassen');
    expect(within(confirmation).getByRole('button', { name: 'Weiter bearbeiten' })).toHaveFocus();
    expect(testService.updateAgreement).not.toHaveBeenCalled();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(within(dialog).queryByRole('group', { name: 'Ungespeicherte Kautionsänderungen' })).not.toBeInTheDocument();
    expect(notes).toHaveValue('Noch zu prüfen');
    expect(linkedContract()).toHaveFocus();
    fireEvent.click(linkedContract());
    fireEvent.click(within(dialog).getByRole('button', { name: 'Weiter bearbeiten' }));
    expect(notes).toHaveValue('Noch zu prüfen');
    expect(screen.getByTestId('guard-route')).toHaveTextContent('/deposits?deposit_id=d-1');

    fireEvent.click(linkedContract());
    const go = within(dialog).getByRole('link', { name: 'Ohne Speichern verlassen' });
    expect(go).toHaveAttribute('href', '/contracts?contract_id=c-1');
    fireEvent.click(go);
    expect(await screen.findByRole('heading', { name: 'Contract navigation reached' })).toBeInTheDocument();
    expect(testService.updateAgreement).not.toHaveBeenCalled();
    expect(screen.queryByRole('dialog', { name: /Kautionsakte/ })).not.toBeInTheDocument();
  });

  it('confirms a dirty close but closes a clean file immediately', async () => {
    const testService = service();
    render(<GuardHarness serviceOverride={testService} />);
    const dialog = await screen.findByRole('dialog', { name: /Kautionsakte/ });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Vereinbarung ändern' }));
    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Notizen' }), { target: { value: 'Lokale Eingabe' } });
    fireEvent.click(within(dialog).getAllByRole('button', { name: 'Schließen' })[0]);
    expect(within(dialog).getByRole('group', { name: 'Ungespeicherte Kautionsänderungen' })).toBeInTheDocument();
    expect(screen.queryByText('Deposit file closed')).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Ohne Speichern verlassen' }));
    expect(screen.getByText('Deposit file closed')).toBeInTheDocument();
    expect(testService.updateAgreement).not.toHaveBeenCalled();
  });

  it('keeps an unmodified file directly navigable without an unnecessary prompt', async () => {
    render(<GuardHarness />);
    await screen.findByRole('dialog', { name: /Kautionsakte/ });
    fireEvent.click(linkedContract());
    expect(screen.getByRole('heading', { name: 'Contract navigation reached' })).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Ungespeicherte Kautionsänderungen' })).not.toBeInTheDocument();
  });
});

describe('unsaved sub-editors and deposit navigation', () => {
  beforeEach(() => { authState.user = { id: 'u-1', role: 'buchhaltung' }; authState.write = null; });

  it.each(['interest', 'security', 'payments', 'settlement'])(
    'keeps unsaved %s values when a linked record is opened until explicitly confirmed', async part => {
      const basic = fileFixture();
      const file = part === 'security'
        ? fileFixture({ money_form: false, deposit: { ...basic.deposit, form: 'guarantee' } })
        : part === 'settlement' ? fileFixture({ settlements: [draftSettlement()] }) : basic;
      render(<GuardHarness file={file} />);
      const dialog = await screen.findByRole('dialog', { name: /Kautionsakte/ });
      if (part === 'interest') {
        const region = within(dialog).getByRole('region', { name: 'Zinsen' });
        fireEvent.click(within(region).getByRole('button', { name: 'Zinssatz hinzufügen' }));
        expect(within(region).getByRole('textbox', { name: 'Zinssatz % p. a.' })).toBeInTheDocument();
      } else if (part === 'security') {
        fireEvent.change(within(dialog).getByRole('textbox', { name: 'Vermerk zur Freigabe' }),
          { target: { value: 'Bestätigung fehlt' } });
      } else if (part === 'payments') {
        fireEvent.click(within(dialog).getByRole('button', { name: 'Zahlung zuordnen' }));
        const list = await within(dialog).findByRole('list', { name: 'Buchungen des Mieters' });
        fireEvent.change(within(list).getByRole('spinbutton', { name: 'Anteil (leer = frei)' }),
          { target: { value: '250' } });
      } else {
        const region = within(dialog).getByRole('region', { name: 'Kautionsabrechnung' });
        fireEvent.change(within(region).getByRole('textbox', { name: 'Notizen' }),
          { target: { value: 'Abrechnung prüfen' } });
      }
      const destination = part === 'security' ? linkedContract()
        : within(dialog).getByRole('link', { name: 'Kaution' });
      expect(unloadWouldPrompt()).toBe(true);
      fireEvent.click(destination);
      expect(screen.getByTestId('guard-route')).toHaveTextContent('/deposits?deposit_id=d-1');
      const confirmation = within(dialog).getByRole('group', { name: 'Ungespeicherte Kautionsänderungen' });
      expect(within(confirmation).getByRole('link', { name: 'Ohne Speichern verlassen' }))
        .toHaveAttribute('href', part === 'security' ? '/contracts?contract_id=c-1' : '/bookings?booking_id=b-1');
      fireEvent.click(within(confirmation).getByRole('button', { name: 'Weiter bearbeiten' }));
      expect(screen.queryByRole('group', { name: 'Ungespeicherte Kautionsänderungen' })).not.toBeInTheDocument();
      if (part === 'security') expect(within(dialog).getByRole('textbox', { name: 'Vermerk zur Freigabe' }))
        .toHaveValue('Bestätigung fehlt');
      if (part === 'settlement') expect(within(dialog).getByRole('textbox', { name: 'Notizen' }))
        .toHaveValue('Abrechnung prüfen');
      if (part === 'payments') expect(within(dialog).getByRole('spinbutton', { name: 'Anteil (leer = frei)' }))
        .toHaveValue(250);
      fireEvent.click(destination);
      fireEvent.click(within(dialog).getByRole('link', { name: 'Ohne Speichern verlassen' }));
      expect(await screen.findByRole('heading', { name: part === 'security'
        ? 'Contract navigation reached' : 'Booking navigation reached' })).toBeInTheDocument();
      expect(unloadWouldPrompt()).toBe(false);
    },
  );

  it('blocks navigation while an agreement save is running and does not warn after successful save', async () => {
    const initial = fileFixture();
    let finish;
    const save = vi.fn(() => new Promise(resolve => { finish = resolve; }));
    const testService = service(initial);
    testService.updateAgreement = save;
    render(<GuardHarness serviceOverride={testService} />);
    const dialog = await screen.findByRole('dialog', { name: /Kautionsakte/ });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Vereinbarung ändern' }));
    const form = within(dialog).getByRole('form', { name: 'Vereinbarung ändern' });
    fireEvent.change(within(form).getByRole('textbox', { name: 'Notizen' }),
      { target: { value: 'Gespeicherter Vermerk' } });
    fireEvent.click(within(form).getByRole('button', { name: 'Speichern' }));
    expect(save).toHaveBeenCalledTimes(1);
    fireEvent.click(linkedContract());
    expect(within(dialog).getByRole('alert')).toHaveTextContent('Kautionsvorgang läuft');
    expect(screen.queryByRole('group', { name: 'Ungespeicherte Kautionsänderungen' })).not.toBeInTheDocument();
    expect(screen.getByTestId('guard-route')).toHaveTextContent('/deposits?deposit_id=d-1');
    await act(async () => {
      finish(fileFixture({ deposit: { ...initial.deposit, revision: 'rev-2', notes: 'Gespeicherter Vermerk' } }));
    });
    await waitFor(() => expect(within(dialog).queryByRole('form', { name: 'Vereinbarung ändern' }))
      .not.toBeInTheDocument());
    fireEvent.click(linkedContract());
    expect(screen.getByRole('heading', { name: 'Contract navigation reached' })).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Ungespeicherte Kautionsänderungen' })).not.toBeInTheDocument();
  });
});

describe('failed and uncertain deposit operations do not bypass the leave guard', () => {
  beforeEach(() => { authState.user = { id: 'u-1', role: 'buchhaltung' }; authState.write = null; });

  it('preserves an edited agreement after a failed save and still requires deliberate navigation', async () => {
    const testService = service();
    testService.updateAgreement.mockRejectedValueOnce(new Error('Sicherung ist offline'));
    render(<GuardHarness serviceOverride={testService} />);
    const dialog = await screen.findByRole('dialog', { name: /Kautionsakte/ });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Vereinbarung ändern' }));
    const form = within(dialog).getByRole('form', { name: 'Vereinbarung ändern' });
    const notes = within(form).getByRole('textbox', { name: 'Notizen' });
    fireEvent.change(notes, { target: { value: 'Wichtiger noch ungesicherter Vermerk' } });
    fireEvent.click(within(form).getByRole('button', { name: 'Speichern' }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Sicherung ist offline');
    fireEvent.click(linkedContract());
    expect(within(dialog).getByRole('group', { name: 'Ungespeicherte Kautionsänderungen' }))
      .toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Weiter bearbeiten' }));
    expect(notes).toHaveValue('Wichtiger noch ungesicherter Vermerk');
    expect(screen.getByTestId('guard-route')).toHaveTextContent('/deposits?deposit_id=d-1');
    expect(testService.updateAgreement).toHaveBeenCalledOnce();
  });

  it('blocks leaving when a settlement finalization outcome is uncertain', async () => {
    const testService = service(fileFixture({ settlements: [draftSettlement()] }));
    testService.finalize.mockRejectedValueOnce(Object.assign(new Error('Antwort verloren'), { isNetwork: true }));
    render(<GuardHarness serviceOverride={testService} />);
    const dialog = await screen.findByRole('dialog', { name: /Kautionsakte/ });
    const section = await within(dialog).findByRole('region', { name: 'Kautionsabrechnung' });
    fireEvent.click(within(section).getByRole('button', { name: 'Prüfen' }));
    await waitFor(() => expect(testService.preview).toHaveBeenCalledOnce());
    fireEvent.click(within(section).getByRole('checkbox'));
    fireEvent.click(within(section).getByRole('button', { name: 'Abschließen' }));
    expect(await within(section).findByText(/Die Antwort ging verloren/)).toBeInTheDocument();
    fireEvent.click(linkedContract());
    expect(await within(dialog).findByText(/Ein Kautionsvorgang läuft noch/)).toHaveAttribute('role', 'alert');
    expect(screen.queryByRole('group', { name: 'Ungespeicherte Kautionsänderungen' })).not.toBeInTheDocument();
    expect(screen.getByTestId('guard-route')).toHaveTextContent('/deposits?deposit_id=d-1');
    expect(testService.finalize).toHaveBeenCalledOnce();
  });
});

function unloadWouldPrompt() {
  const event = new Event('beforeunload', { cancelable: true });
  window.dispatchEvent(event);
  return event.defaultPrevented;
}

describe('browser unload protection for deposit editors', () => {
  beforeEach(() => { authState.user = { id: 'u-1', role: 'buchhaltung' }; authState.write = null; });

  it('activates only for unsaved changes, stays active through cancel, and disarms after reverting the edit form', async () => {
    render(<GuardHarness />);
    const dialog = await screen.findByRole('dialog', { name: /Kautionsakte/ });
    expect(unloadWouldPrompt()).toBe(false);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Vereinbarung ändern' }));
    const form = within(dialog).getByRole('form', { name: 'Vereinbarung ändern' });
    expect(unloadWouldPrompt()).toBe(false);
    const notes = within(form).getByRole('textbox', { name: 'Notizen' });
    fireEvent.change(notes, { target: { value: 'Eine neue Eingabe' } });
    expect(unloadWouldPrompt()).toBe(true);
    fireEvent.click(linkedContract());
    expect(unloadWouldPrompt()).toBe(true);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Weiter bearbeiten' }));
    expect(unloadWouldPrompt()).toBe(true);
    expect(notes).toHaveValue('Eine neue Eingabe');
    fireEvent.click(within(form).getByRole('button', { name: 'Abbrechen' }));
    expect(unloadWouldPrompt()).toBe(false);
    expect(screen.getByTestId('guard-route')).toHaveTextContent('/deposits?deposit_id=d-1');
  });

  it('protects a pending command even without changed inputs, then disarms after a successful response', async () => {
    const original = fileFixture();
    let finish;
    const api = service(original);
    api.startSettlement = vi.fn(() => new Promise(resolve => { finish = resolve; }));
    render(<GuardHarness serviceOverride={api} />);
    const dialog = await screen.findByRole('dialog', { name: /Kautionsakte/ });
    expect(unloadWouldPrompt()).toBe(false);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Kautionsabrechnung beginnen' }));
    expect(api.startSettlement).toHaveBeenCalledOnce();
    expect(unloadWouldPrompt()).toBe(true);
    await act(async () => { finish(fileFixture({ settlements: [draftSettlement()] })); });
    await waitFor(() => expect(unloadWouldPrompt()).toBe(false));
    expect(screen.getByRole('dialog', { name: /Kautionsakte/ })).toBeInTheDocument();
  });

  it('keeps unload protection after a failed save until a confirmed clean state', async () => {
    const api = service();
    api.updateAgreement.mockRejectedValueOnce(new Error('Sicherung fehlgeschlagen'));
    render(<GuardHarness serviceOverride={api} />);
    const dialog = await screen.findByRole('dialog', { name: /Kautionsakte/ });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Vereinbarung ändern' }));
    const form = within(dialog).getByRole('form', { name: 'Vereinbarung ändern' });
    const notes = within(form).getByRole('textbox', { name: 'Notizen' });
    fireEvent.change(notes, { target: { value: 'Bitte nicht verlieren' } });
    fireEvent.click(within(form).getByRole('button', { name: 'Speichern' }));
    await within(dialog).findByText('Sicherung fehlgeschlagen');
    expect(within(dialog).getByRole('alert')).toHaveTextContent('Sicherung fehlgeschlagen');
    expect(unloadWouldPrompt()).toBe(true);
    expect(notes).toHaveValue('Bitte nicht verlieren');
    fireEvent.click(within(form).getByRole('button', { name: 'Abbrechen' }));
    expect(unloadWouldPrompt()).toBe(false);
  });

  it('continues to protect an uncertain settlement finalization after the network request has stopped', async () => {
    const api = service(fileFixture({ settlements: [draftSettlement()] }));
    api.finalize.mockRejectedValueOnce(Object.assign(new Error('Ungewiss'), { isNetwork: true }));
    render(<GuardHarness serviceOverride={api} />);
    const section = await screen.findByRole('region', { name: 'Kautionsabrechnung' });
    expect(unloadWouldPrompt()).toBe(false);
    fireEvent.click(within(section).getByRole('button', { name: 'Prüfen' }));
    await waitFor(() => expect(api.preview).toHaveBeenCalledOnce());
    fireEvent.click(within(section).getByRole('checkbox'));
    fireEvent.click(within(section).getByRole('button', { name: 'Abschließen' }));
    expect(await within(section).findByText(/Die Antwort ging verloren/)).toBeInTheDocument();
    expect(unloadWouldPrompt()).toBe(true);
    expect(api.finalize).toHaveBeenCalledOnce();
  });

  it('removes the unload listener on unmount so later pages can reload normally', async () => {
    const view = render(<GuardHarness />);
    const dialog = await screen.findByRole('dialog', { name: /Kautionsakte/ });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Vereinbarung ändern' }));
    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Notizen' }),
      { target: { value: 'Nicht gespeichert' } });
    expect(unloadWouldPrompt()).toBe(true);
    view.unmount();
    expect(unloadWouldPrompt()).toBe(false);
  });
});
