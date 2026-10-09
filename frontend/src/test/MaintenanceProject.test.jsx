import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import MaintenanceProject from '../features/maintenanceProject/MaintenanceProject';
import { de, en, es } from '../features/maintenanceProject/text';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), getBlob: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key, locale: 'de-DE' }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => async () => true }));
vi.mock('../components/PhotoDropZone', () => ({ default: () => null }));
vi.mock('../components/FileViewer', () => ({ default: () => null }));
vi.mock('../components/PdfPreview', () => ({ default: ({ url }) => <div data-testid="pdf">{url}</div> }));

const ALL = {
  edit_case: true, transition: true, plan: true, appointments: true, participants: true, record_quotes: true,
  decide_quotes: true, manage_orders: true, propose_change_orders: true, decide_change_orders: true,
  link_invoices: true, create_invoices: true, allocate_payments: true, write_protocols: true,
  finalize_protocols: true, documents: true, photos: true,
};
const TECHNICIAN = { ...ALL, decide_quotes: false, manage_orders: false, decide_change_orders: false,
  link_invoices: false, create_invoices: false, allocate_payments: false };

function project(abilities = ALL) {
  return {
    case: { id: 'c1', title: 'Dachschaden nach Sturm', status: 'in_progress', priority: 'high', property_id: 'p1',
            unit_id: 'u1', property_name: 'Haus Nord', unit_label: 'WE 3', estimated_cost: 1500, updated_at: '2026-10-08T10:00:00Z' },
    workflow: { status: 'in_progress', allowed: [
      { status: 'open', reason_required: false, blockers: [] },
      { status: 'completed', reason_required: false, blockers: ['Arbeitspakete sind noch offen: „Dach“.'] },
      { status: 'cancelled', reason_required: true, blockers: [] }] },
    history: [{ id: 'h1', old_value: null, new_value: 'open', changed_at: '2026-10-01T08:00:00Z', changed_by_name: 'Owner', reason: 'Angelegt' }],
    work_packages: [
      { id: 'a', title: 'Gerüst', kind: 'work', status: 'done', predecessors: [], successors: ['b'], blocked_by: [], order_ids: [] },
      { id: 'b', title: 'Dach', kind: 'work', status: 'planned', predecessors: ['a'], successors: [], blocked_by: [], order_ids: ['o1'],
        planned_start: '2026-03-05', planned_end: '2026-03-20' },
    ],
    dependencies: [{ id: 'd1', predecessor_id: 'a', successor_id: 'b' }],
    schedule_conflicts: [{ predecessor_id: 'a', successor_id: 'b', message: '„Dach“ beginnt am 05.03.2026, vor dem geplanten Ende von „Gerüst“ (10.03.2026).' }],
    participants: [{ id: 'pa1', role: 'contractor', trade: 'Dach', contact: { id: 'k1', name: 'Dach Müller GmbH', phone: '0351 123' } }],
    appointments: [{ id: 'ap1', kind: 'inspection', event: { id: 'e1', title: 'Begehung', event_date: '2026-06-01', event_time: '09:30' }, contact: null }],
    quotes: [{ id: 'q1', supplier_name: 'Dach Schulze', quote_date: '2026-04-01', net_amount: 1100, gross_amount: 1309, status: 'received', expired: true }],
    orders: [{ id: 'o1', order_number: 'A-1', supplier_name: 'Dach Müller GmbH', order_date: '2026-04-10', gross_amount: 1190,
               status: 'active', change_orders: [{ id: 'co1', title: 'Lattung', gross_amount: 238, status: 'proposed' }] }],
    invoices: [{ link_id: 'l1', order_id: 'o1', paid: 1000, payments: [{ id: 'pay1', amount: 1000, booking: { booking_date: '2026-05-03', payment_text: 'Abschlag' } }],
                 invoice: { id: 'i1', invoice_number: 'R-1', supplier: 'Dach Müller GmbH', invoice_date: '2026-05-01', gross_amount: 1190, status: 'open' } }],
    protocols: [
      { id: 'pr1', protocol_type: 'acceptance', protocol_date: '2026-06-10', status: 'draft', result: 'accepted_with_defects',
        defects: [{ title: 'Riss', severity: 'major', photo_ids: [] }], photo_ids: [], integrity: 'draft' },
      { id: 'pr2', protocol_type: 'inspection', protocol_date: '2026-05-10', status: 'final', defects: [], photo_ids: [],
        integrity: 'verified', file_url: '/uploads/maintenance-protocols/x.pdf' },
    ],
    documents: [{ link_id: null, role: 'protocol', source: 'protocol', document: { id: 'doc1', title: 'Begehungsprotokoll', file_url: '/uploads/x.pdf' } }],
    photos: [],
    costs: { budget: 1500, ordered: 1190, pending_change_orders: 238, invoiced: 1190, paid: 1000, open_to_invoice: 0,
             open_to_pay: 190, remaining_budget: 310, warnings: [{ code: 'x', message: 'Eine zugeordnete Zahlung wurde (teilweise) storniert.' }],
             orders: [{ order_id: 'o1', status: 'active', ordered: 1190, invoiced: 1190, paid: 1000 }], invoice_paid: { i1: 1000 } },
    abilities,
  };
}

function show(abilities) {
  api.get.mockImplementation(path => {
    if (path.endsWith('/project')) return Promise.resolve(project(abilities));
    if (path.includes('/payments/candidates')) return Promise.resolve({ items: [
      { id: 'b9', booking_date: '2026-05-20', amount: -500, payment_text: 'Dach Müller Rest', free: 500 }], has_more: false });
    return Promise.resolve({ items: [], has_more: false });
  });
  api.list.mockResolvedValue([{ id: 'k1', company_name: 'Dach Müller GmbH', contact_type: 'supplier' }]);
  return render(<MemoryRouter><MaintenanceProject caseId="c1" /></MemoryRouter>);
}

const tab = name => fireEvent.click(screen.getByRole('tab', { name }));

beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);

describe('maintenance project file', () => {
  it('shows the case as a project with costs, workflow gates and all seven sections', async () => {
    const { container } = show();
    expect(await screen.findByRole('heading', { name: 'Dachschaden nach Sturm' })).toBeInTheDocument();
    expect(screen.getAllByRole('tab').map(item => item.textContent)).toEqual([
      'Übersicht', 'Arbeitspakete & Abhängigkeiten', 'Termine', 'Angebote, Aufträge & Nachträge',
      'Rechnungen & Kosten', 'Protokolle', 'Dokumente']);
    const kpis = within(container.querySelector('.mp-kpis'));
    expect(kpis.getByText('1.500,00 €')).toBeInTheDocument();       // budget
    expect(kpis.getByText('1.000,00 €')).toBeInTheDocument();       // paid, from the bookings
    expect(screen.getByRole('button', { name: 'Akte abschließen' })).toBeDisabled();
    expect(screen.getByText(/Arbeitspakete sind noch offen/)).toBeInTheDocument();
    expect(screen.getByText('Eine zugeordnete Zahlung wurde (teilweise) storniert.')).toBeInTheDocument();
    expect(screen.getByText('Dach Müller GmbH')).toBeInTheDocument();          // craftsman of the address book

    tab('Arbeitspakete & Abhängigkeiten');
    expect(screen.getByText(/beginnt am 05.03.2026/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Abhängigkeit entfernen: Gerüst' })).toBeInTheDocument();
    tab('Angebote, Aufträge & Nachträge');
    expect(screen.getByText('abgelaufen')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Beauftragen' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Genehmigen' })).toBeInTheDocument();
    tab('Protokolle');
    expect(screen.getByText('Original geprüft')).toBeInTheDocument();
  });

  it('shows the German refusal of a cycle where the dependency was entered', async () => {
    show();
    await screen.findByRole('heading', { name: 'Dachschaden nach Sturm' });
    tab('Arbeitspakete & Abhängigkeiten');
    api.post.mockRejectedValueOnce(new Error('Abhängigkeit abgelehnt: Sie würde einen Kreis bilden („Dach“ → „Gerüst“ → „Dach“).'));
    fireEvent.click(screen.getByRole('button', { name: 'Abhängigkeit hinzufügen' }));
    const dialog = screen.getByRole('dialog', { name: 'Abhängigkeit hinzufügen' });
    fireEvent.change(within(dialog).getByLabelText(/Vorgänger/), { target: { value: 'b' } });
    fireEvent.change(within(dialog).getByLabelText(/Nachfolger/), { target: { value: 'a' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'ui.buttons.save' }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Kreis bilden („Dach“ → „Gerüst“ → „Dach“)');
    expect(api.post).toHaveBeenCalledWith('/maintenance/c1/dependencies', { predecessor_id: 'b', successor_id: 'a' });
  });

  it('offers a technician the site work but not the commercial decisions', async () => {
    show(TECHNICIAN);
    await screen.findByRole('heading', { name: 'Dachschaden nach Sturm' });
    tab('Angebote, Aufträge & Nachträge');
    expect(screen.getByRole('button', { name: 'Angebot erfassen' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Beauftragen' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Genehmigen' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Stornieren' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Nachtrag erfassen' })).toBeInTheDocument();
    tab('Rechnungen & Kosten');
    expect(screen.queryByRole('button', { name: 'Neue Rechnung erfassen' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Zahlung zuordnen' })).not.toBeInTheDocument();
    tab('Protokolle');
    expect(screen.getByRole('button', { name: 'Abschließen & archivieren' })).toBeInTheDocument();
  });

  it('is read-only without write rights', async () => {
    show(Object.fromEntries(Object.keys(ALL).map(key => [key, false])));
    await screen.findByRole('heading', { name: 'Dachschaden nach Sturm' });
    expect(screen.getByText(/Nur Lesen/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Akte abbrechen' })).not.toBeInTheDocument();
    tab('Arbeitspakete & Abhängigkeiten');
    expect(screen.queryByRole('button', { name: 'Arbeitspaket anlegen' })).not.toBeInTheDocument();
  });

  it('finalizes a protocol with one command key, also when the first answer is lost', async () => {
    show();
    await screen.findByRole('heading', { name: 'Dachschaden nach Sturm' });
    tab('Protokolle');
    api.post.mockRejectedValueOnce(new Error('Verbindung zum Server fehlgeschlagen.')).mockResolvedValueOnce({ status: 'final' });
    fireEvent.click(screen.getByRole('button', { name: 'Abschließen & archivieren' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Verbindung zum Server fehlgeschlagen.');
    fireEvent.click(screen.getByRole('button', { name: 'Abschließen & archivieren' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2));
    const [first, second] = api.post.mock.calls;
    expect(first[0]).toBe('/maintenance/c1/protocols/pr1/finalize');
    expect(second[1].idempotency_key).toBe(first[1].idempotency_key);
    expect(await screen.findByRole('status')).toHaveTextContent('Protokoll abgeschlossen und archiviert.');
  });

  it('allocates a payment from a paged lookup of bookings', async () => {
    show();
    await screen.findByRole('heading', { name: 'Dachschaden nach Sturm' });
    tab('Rechnungen & Kosten');
    expect(screen.getByText(/die Akte bucht nichts selbst/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Zahlung zuordnen' }));
    const picker = await screen.findByRole('dialog', { name: 'Zahlung zuordnen' });
    expect(await within(picker).findByText(/Dach Müller Rest/)).toBeInTheDocument();
    expect(api.get.mock.calls.some(([path]) => path.startsWith('/invoices/i1/payments/candidates?skip=0&limit=25'))).toBe(true);
    fireEvent.click(within(picker).getByRole('button', { name: 'Auswählen' }));
    const form = await screen.findByRole('dialog', { name: /Zahlung zuordnen: 20.05.2026/ });
    expect(within(form).getByLabelText(/Betrag/)).toHaveValue(190);     // what the invoice still lacks
    api.post.mockResolvedValueOnce({ id: 'pay2' });
    fireEvent.click(within(form).getByRole('button', { name: 'ui.buttons.save' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/invoices/i1/payments', { booking_id: 'b9', amount: 190 }));
  });

  it('has every text in German, English and Spanish', () => {
    const keys = Object.keys(de).sort();
    expect(Object.keys(en).sort()).toEqual(keys);
    expect(Object.keys(es).sort()).toEqual(keys);
    for (const dictionary of [de, en, es]) {
      expect(Object.values(dictionary).filter(value => typeof value !== 'string' || !value.trim())).toEqual([]);
    }
  });
});
