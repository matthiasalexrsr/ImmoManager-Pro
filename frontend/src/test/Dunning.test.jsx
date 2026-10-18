import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import Dunning from '../pages/Dunning';
import DunningCase from '../pages/DunningCase';
import { api } from '../api';
import { COPY, dunningText } from '../features/dunning/dunningText';

vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(),
  getBlob: vi.fn() } }));
const i18n = vi.hoisted(() => ({ locale: 'de-DE' }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key, locale: i18n.locale }) }));
const access = vi.hoisted(() => ({ canWrite: true }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => access.canWrite, useAuth: () => null }));
vi.mock('../components/PdfPreview', () => ({ default: ({ title }) => <div>PDF {title}</div> }));

const OVERVIEW = {
  counts: { open_cases: 1, drafts: 1, outbox_ready: 0, replies_review: 2, active_blocks: 0 }, total: 1, items: [{
    id: 'c1', reference: 'M-2026-3F6ED2C4', contract_id: 'k1', status: 'open', stage: 1, stage_label: 'Zahlungserinnerung',
    contract_number: 'V-1', tenant_name: 'Max Muster', property_name: 'Nordhaus', outstanding: 1006.28, drafts: 1,
    next_status: 'draft_pending', next_stage: 2, due_on: '2026-07-25' }],
};

const LETTER_DRAFT = { id: 'l2', case_id: 'c1', stage: 2, stage_label: '1. Mahnung', status: 'draft',
  reference: 'M-2026-3F6ED2C4', letter_date: '2026-07-25', payment_deadline: '2026-08-08', principal: 1000,
  earlier_charges: 0, fee: 2.5, interest: 3.78, total: 1006.28, outbox: { status: 'queued' } };

const FILE = {
  contract: { id: 'k1', number: 'V-1', property: 'Nordhaus', unit: 'W1', tenant_name: 'Max Muster', tenant_id: 't1' },
  as_of: '2026-07-26',
  claims: [{ key: 'rent:2026-07', kind: 'rent', description: 'Miete 07/2026', due_date: '2026-07-03', amount: 1000,
    paid: 0, outstanding: 1000 }],
  excluded: [{ key: 'receivable:r1', description: 'Nachzahlung NK 2025', amount: 150, reason: 'objection',
    reason_label: 'Widerspruch gegen die Nebenkostenabrechnung noch nicht entschieden' }],
  manual: [],
  totals: { overdue_principal: 1000, open_charges: 0, unapplied_payments: 0 },
  blocks: [], disputes: [],
  cases: [{ id: 'c1', reference: 'M-2026-3F6ED2C4', status: 'open', stage: 1, stage_label: 'Zahlungserinnerung',
    outstanding: 1000, letters: [
      { id: 'l1', case_id: 'c1', stage: 1, stage_label: 'Zahlungserinnerung', status: 'final', reference: 'M-2026-3F6ED2C4',
        letter_date: '2026-07-10', payment_deadline: '2026-07-24', principal: 1000, earlier_charges: 0, fee: 0, interest: 0,
        total: 1000, outbox: { status: 'sent' } },
      LETTER_DRAFT] }],
  next: { status: 'draft_pending', next_stage: 2, next_stage_label: '1. Mahnung', reason: 'Ein Entwurf ist offen.',
    excluded: [], letter: null },
};

function RouteMarker() { const location = useLocation(); return <span data-testid="dunning-route">{location.pathname + location.search}</span>; }

function showCase(file = FILE, contractId = 'k1') {
  api.get.mockImplementation(path => {
    if (path === `/dunning/contracts/${encodeURIComponent(contractId)}`) return Promise.resolve(file);
    if (path === '/dunning/letters/l2') return Promise.resolve({ ...LETTER_DRAFT, draft_hash: 'a'.repeat(64) });
    if (path.startsWith('/dunning/cases/c1/timeline')) {
      const after = new URLSearchParams(path.split('?')[1]).get('after');
      return Promise.resolve(after ? { items: [{ id: 'e3', at: '2026-07-15T10:00:00', summary: 'Eingang', reply: { body: 'Zahle Freitag' } }],
        total: 3, has_more: false, next_after: null }
        : { items: [{ id: 'e1', at: '2026-07-10T10:00:00', summary: 'Mahnakte angelegt' },
          { id: 'e2', at: '2026-07-10T10:01:00', summary: 'Zahlungserinnerung abgeschlossen' }],
        total: 3, has_more: true, next_after: 'cursor-1' });
    }
    return Promise.reject(new Error(`unexpected ${path}`));
  });
  return render(<MemoryRouter initialEntries={[`/dunning/contracts/${encodeURIComponent(contractId)}`]}>
    <RouteMarker />
    <Routes><Route path="/dunning/contracts/:contractId" element={<DunningCase />} />
      <Route path="*" element={<p>Verknüpfte Zielseite</p>} /></Routes>
  </MemoryRouter>);
}

beforeEach(() => {
  vi.clearAllMocks();
  access.canWrite = true;
  i18n.locale = 'de-DE';
  api.list.mockResolvedValue([{ id: 'p1', name: 'Nord' }]);
});

describe('dunning texts', () => {
  it('has the same keys in German, English and Spanish', () => {
    const keys = Object.keys(COPY['de-DE']).sort();
    expect(Object.keys(COPY['en-US']).sort()).toEqual(keys);
    expect(Object.keys(COPY['es-ES']).sort()).toEqual(keys);
    expect(dunningText('en-US', 'due', { count: 3 })).toBe('Letters due: 3');
    expect(dunningText('xx', 'title')).toBe('Mahnwesen');
  });
});

describe('dunning overview', () => {
  it('shows the counts and the open cases with their next step', async () => {
    api.get.mockResolvedValue(OVERVIEW);
    render(<MemoryRouter><Dunning /></MemoryRouter>);
    expect(await screen.findByText('M-2026-3F6ED2C4')).toBeInTheDocument();
    expect(screen.getByText('Eingänge zu prüfen').parentElement).toHaveTextContent('2');
    expect(screen.getByText(/Nächster Schritt: Entwurf offen/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Akte öffnen' })).toHaveAttribute('href', '/dunning/contracts/k1');
  });

  it('previews a run, shows what is excluded and creates it with the reviewed hash', async () => {
    api.get.mockResolvedValue(OVERVIEW);
    api.post.mockImplementation(path => {
      if (path === '/dunning/preview') return Promise.resolve({ preview_hash: 'b'.repeat(64), due_count: 1,
        totals: { principal: 1000, earlier_charges_total: 0, fee: 2.5, interest: 3.78, total: 1006.28 },
        entries: [{ contract_id: 'k1', contract_number: 'V-1', status: 'due', next_stage_label: '1. Mahnung',
          letter: { principal: 1000, earlier_charges_total: 0, fee: 2.5, interest: 3.78, total: 1006.28 },
          excluded: [{ description: 'Nachzahlung', reason_label: 'Widerspruch' }] }] });
      if (path === '/dunning/runs') return Promise.resolve({ letters: [{ id: 'l2' }] });
      return Promise.reject(new Error(path));
    });
    render(<MemoryRouter><Dunning /></MemoryRouter>);
    fireEvent.click(screen.getByRole('tab', { name: 'Mahnlauf' }));
    const calculate = screen.getByRole('button', { name: 'Vorschau berechnen' });
    await waitFor(() => expect(calculate).toBeEnabled());
    fireEvent.click(calculate);
    expect(await screen.findByText('Fällige Schreiben: 1')).toBeInTheDocument();
    expect(screen.getByText(/Nachzahlung \(Widerspruch\)/)).toBeInTheDocument();
    expect(api.post).toHaveBeenCalledTimes(1);           // a preview stores nothing
    fireEvent.click(screen.getByRole('button', { name: 'Mahnlauf anlegen' }));
    expect(await screen.findByText('Mahnlauf angelegt: 1 Entwürfe.')).toBeInTheDocument();
    const [, body] = api.post.mock.calls[1];
    expect(body.preview_hash).toBe('b'.repeat(64));
    expect(body.portfolio_id).toBe('p1');
    expect(body.command_key).toMatch(/^run-/);
  });

  it('is read only without the dunning write area', async () => {
    access.canWrite = false;
    api.get.mockResolvedValue({ stages: [{ stage: 1, label: 'Erinnerung', days_after: 7, fee: 0,
      payment_deadline_days: 14, charge_interest: false }], base_rates: [] });
    render(<MemoryRouter><Dunning /></MemoryRouter>);
    expect(screen.getByRole('note')).toHaveTextContent('Nur Lesezugriff');
    fireEvent.click(screen.getByRole('tab', { name: 'Einstellungen' }));
    expect(await screen.findByLabelText('Bezeichnung 1')).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Stufen speichern' })).toBeNull();
  });

  it('records a reply and offers review items for assignment by reference', async () => {
    api.get.mockResolvedValue({ total: 1, items: [{ id: 'r1', received_on: '2026-07-15', sender: 'Max', body: 'Ich zahle.',
      status: 'review', review_reason: 'no_reference' }] });
    api.post.mockResolvedValue({ status: 'review', review_reason: 'no_reference' });
    render(<MemoryRouter><Dunning /></MemoryRouter>);
    fireEvent.click(screen.getByRole('tab', { name: 'Eingänge' }));
    const item = await screen.findByText('Ich zahle.');
    expect(within(item.closest('li')).getByText('kein Aktenzeichen')).toBeInTheDocument();
    fireEvent.change(within(item.closest('li')).getByLabelText('Mahnakte (Aktenzeichen)'),
      { target: { value: 'm-2026-3f6ed2c4 ' } });
    fireEvent.click(within(item.closest('li')).getByRole('button', { name: 'Zuordnen' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/dunning/replies/r1/assign', { reference: 'm-2026-3f6ed2c4' }));
  });
});

describe('dunning case file', () => {
  it('links a dunning file to its exact contract, claims, tenant account and tenant transactions', async () => {
    showCase();
    await screen.findByRole('heading', { name: /Mahnakte/ });
    const nav = screen.getByRole('navigation', { name: dunningText('de-DE', 'relatedPages') });
    expect(within(nav).getByText('Direkt weiter')).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Mietvertrag öffnen' }))
      .toHaveAttribute('href', '/contracts?contract_id=k1');
    expect(within(nav).getByRole('link', { name: 'Forderungen dieses Vertrags' }))
      .toHaveAttribute('href', '/receivables?contract_id=k1');
    expect(within(nav).getByRole('link', { name: 'Mieterkonto öffnen' }))
      .toHaveAttribute('href', '/tenants/t1/account');
    expect(within(nav).getByRole('link', { name: 'Buchungen dieses Mieters' }))
      .toHaveAttribute('href', '/bookings?tenant_id=t1');
    expect(within(nav).getAllByRole('link')).toHaveLength(4);
    fireEvent.click(within(nav).getByRole('link', { name: 'Forderungen dieses Vertrags' }));
    expect(screen.getByTestId('dunning-route')).toHaveTextContent('/receivables?contract_id=k1');
    expect(api.post).not.toHaveBeenCalled();
    expect(api.put).not.toHaveBeenCalled();
  });

  it('omits tenant-specific destinations when the backend has not supplied a tenant ID', async () => {
    showCase({ ...FILE, contract: { ...FILE.contract, tenant_id: null } });
    await screen.findByRole('heading', { name: /Mahnakte/ });
    const nav = screen.getByRole('navigation', { name: 'Verknüpfte Seiten' });
    expect(within(nav).getAllByRole('link')).toHaveLength(2);
    expect(within(nav).queryByRole('link', { name: 'Mieterkonto öffnen' })).not.toBeInTheDocument();
    expect(within(nav).queryByRole('link', { name: 'Buchungen dieses Mieters' })).not.toBeInTheDocument();
    // Property and unit display names are NOT their IDs in the dunning response.
    expect(within(nav).queryByRole('link', { name: /Nordhaus|W1/ })).not.toBeInTheDocument();
  });

  it('URL-encodes unusual real contract and tenant IDs for contextual navigation', async () => {
    const file = { ...FILE, contract: { ...FILE.contract, id: 'k /1', tenant_id: 't+#1' } };
    showCase(file, 'k /1');
    await screen.findByRole('heading', { name: /Mahnakte/ });
    expect(api.get).toHaveBeenCalledWith('/dunning/contracts/k%20%2F1', expect.anything());
    const nav = screen.getByRole('navigation', { name: 'Verknüpfte Seiten' });
    expect(within(nav).getByRole('link', { name: 'Mietvertrag öffnen' }))
      .toHaveAttribute('href', '/contracts?contract_id=k%20%2F1');
    expect(within(nav).getByRole('link', { name: 'Forderungen dieses Vertrags' }))
      .toHaveAttribute('href', '/receivables?contract_id=k%20%2F1');
    expect(within(nav).getByRole('link', { name: 'Mieterkonto öffnen' }))
      .toHaveAttribute('href', '/tenants/t%2B%231/account');
    expect(within(nav).getByRole('link', { name: 'Buchungen dieses Mieters' }))
      .toHaveAttribute('href', '/bookings?tenant_id=t%2B%231');
  });

  it.each(['de-DE', 'en-US', 'es-ES'])('localizes every related page link for %s', async locale => {
    i18n.locale = locale;
    showCase();
    await screen.findByRole('heading', { name: new RegExp(dunningText(locale, 'contractFile')) });
    const nav = screen.getByRole('navigation', { name: dunningText(locale, 'relatedPages') });
    expect(within(nav).getByText(dunningText(locale, 'nextPages'))).toBeInTheDocument();
    for (const key of ['openContract', 'contractReceivables', 'openTenantAccount', 'tenantBookings']) {
      expect(within(nav).getByRole('link', { name: dunningText(locale, key) })).toBeInTheDocument();
    }
  });

  it('shows claims, exclusions and letters, and finalizes a draft only after confirmation', async () => {
    api.post.mockResolvedValue({});
    showCase();
    expect(await screen.findByRole('cell', { name: 'Miete 07/2026' })).toBeInTheDocument();
    expect(screen.getByText(/Widerspruch gegen die Nebenkostenabrechnung/)).toBeInTheDocument();
    const draft = screen.getByText('1. Mahnung · 25.07.2026').closest('li');
    const finalize = within(draft).getByRole('button', { name: 'Abschließen' });
    expect(finalize).toBeDisabled();
    fireEvent.click(within(draft).getByRole('checkbox'));
    fireEvent.change(within(draft).getByLabelText('Versandweg'), { target: { value: 'email' } });
    fireEvent.click(finalize);
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/dunning/letters/l2/finalize', expect.objectContaining({
      draft_hash: 'a'.repeat(64), channel: 'email', confirmed: true })));
  });

  it('reads a long timeline page by page', async () => {
    showCase();
    fireEvent.click(await screen.findByRole('button', { name: 'Verlauf' }));
    expect(await screen.findByText(/Mahnakte angelegt/)).toBeInTheDocument();
    expect(screen.getByText('(2 von 3)')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Weitere laden' }));
    expect(await screen.findByText('Zahle Freitag')).toBeInTheDocument();
    expect(screen.getByText('(3 von 3)')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Weitere laden' })).toBeNull();
  });

  it('opens the letter PDF in the in-page preview', async () => {
    api.getBlob.mockResolvedValue(new Blob(['%PDF-1.4'], { type: 'application/pdf' }));
    globalThis.URL.createObjectURL = vi.fn(() => 'blob:letter');
    globalThis.URL.revokeObjectURL = vi.fn();
    showCase();
    const first = (await screen.findByText('Zahlungserinnerung · 10.07.2026')).closest('li');
    fireEvent.click(within(first).getByRole('button', { name: 'PDF ansehen' }));
    expect(await screen.findByText('PDF Zahlungserinnerung M-2026-3F6ED2C4')).toBeInTheDocument();
    expect(api.getBlob).toHaveBeenCalledWith('/dunning/letters/l1/pdf');
  });

  it('sets a dunning block with reason and date', async () => {
    api.post.mockResolvedValue({});
    showCase();
    const form = await screen.findByRole('form', { name: 'Mahnsperre setzen' });
    fireEvent.change(within(form).getByLabelText('Grund'), { target: { value: 'Ratenzahlung' } });
    fireEvent.change(within(form).getByLabelText('Gesperrt bis'), { target: { value: '2026-12-31' } });
    fireEvent.submit(form);
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/dunning/contracts/k1/blocks',
      { reason: 'Ratenzahlung', blocked_until: '2026-12-31' }));
  });
});
