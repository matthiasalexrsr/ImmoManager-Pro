import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import Invoices from '../pages/Invoices';
import PropertyDetail from '../pages/PropertyDetail';
import UnitOverview from '../pages/UnitOverview';
import { api } from '../api';
import { workspace } from '../utils/workspaceClient';

const state = vi.hoisted(() => ({ properties: [], units: [], contracts: [], invoices: [], taxRates: [], views: [] }));
vi.mock('../api', () => ({ api: { list: vi.fn(), get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => ({
  'ui.buttons.new': 'Neu', 'ui.buttons.create': 'Erstellen', 'ui.buttons.save': 'Speichern',
  'ui.buttons.edit': 'Bearbeiten', 'ui.buttons.cancel': 'Abbrechen',
}[key]), locale: 'de-DE' }) }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'finance-viewer' } }), useCanWrite: () => true }));
vi.mock('../contexts/DataStoreContext', () => ({
  useEntities: kind => ({ items: state[kind] || [], loading: false, error: null }),
  useDataStore: () => ({ invalidateRelated: () => {} }),
}));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => async () => true }));
vi.mock('../components/PhotoDropZone', () => ({ default: () => null }));
vi.mock('../components/FileViewer', () => ({ default: () => null }));
vi.mock('../utils/workspaceClient', async original => ({ ...await original(), workspace: {
  list: vi.fn(), get: vi.fn(), put: vi.fn(), remove: vi.fn(), touch: vi.fn(), command: () => crypto.randomUUID(),
} }));

function Location() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname + location.search}</output>;
}
function show(path = '/invoices') {
  window.history.replaceState({}, '', path);
  return render(<MemoryRouter initialEntries={[path]}><Location /><Routes>
    <Route path="/invoices" element={<Invoices />} />
    <Route path="/properties/:id" element={<PropertyDetail />} />
    <Route path="/units/:id" element={<UnitOverview />} />
    <Route path="/reports" element={<h1>Auswertungen</h1>} />
  </Routes></MemoryRouter>);
}
const currentParams = () => new URL(screen.getByTestId('location').textContent, 'http://localhost').searchParams;
const unit = (id, rent, extra = {}) => ({ id, property_id: 'p1', label: `Einheit ${id}`, unit_type: 'apartment',
  area_sqm: 50, cold_rent: rent, service_charge_advance: 0, heating_advance: 0, ...extra });
const invoice = (id, property, status, amount) => ({ id, property_id: property, status, supplier: `Lieferant ${id}`,
  invoice_number: `RE-${id}`, invoice_date: '2026-10-01', net_amount: amount, vat_rate: 0, vat_amount: 0, gross_amount: amount,
  payment_summary: { status, paid: status === 'paid' ? amount : 0,
    open: ['paid', 'cancelled'].includes(status) ? 0 : amount, overdue: status === 'overdue', due_on: null, note: null } });
const stat = name => screen.getByRole('button', { name }).querySelector('.stat-value');

beforeEach(() => {
  vi.resetAllMocks(); localStorage.clear(); sessionStorage.clear();
  state.properties = [{ id: 'p1', name: 'Gleiches Haus', status: 'active' }, { id: 'p2', name: 'Gleiches Haus', status: 'active' }];
  state.units = [unit('u1', 500)]; state.contracts = []; state.invoices = []; state.taxRates = []; state.views = [];
  api.list.mockImplementation(async path => {
    const resource = path.split('?')[0];
    if (resource === '/invoices' || resource === '/invoices/overview') return state.invoices;
    if (resource === '/units') return state.units;
    if (resource === '/contracts') return state.contracts;
    return [];
  });
  api.get.mockImplementation(async path => {
    if (path.startsWith('/properties/')) return state.properties.find(row => row.id === decodeURIComponent(path.split('/').pop()));
    if (path.startsWith('/units/')) return state.units.find(row => row.id === decodeURIComponent(path.split('/').pop()));
    return {};
  });
  api.post.mockResolvedValue({ id: 'created' }); api.put.mockResolvedValue({});
  workspace.list.mockImplementation(async resource => ({ items: resource === 'views' ? state.views : [], next_cursor: null }));
  workspace.get.mockRejectedValue(Object.assign(new Error('Nicht gespeichert'), { statusCode: 404 }));
  workspace.put.mockImplementation(async (_resource, id, body) => ({ ...body, id, revision: 1 }));
  workspace.remove.mockResolvedValue({ deleted: true }); workspace.touch.mockResolvedValue({});
});
afterEach(() => { cleanup(); window.history.replaceState({}, '', '/'); });

describe('invoice object identity and explicit zero amounts', () => {
  it('opens the exact invoices of a same-named property and scopes its KPI sources', async () => {
    state.invoices = [invoice('a', 'p1', 'open', 10), invoice('b', 'p2', 'open', 99)];
    show('/properties/p1?tab=finance');
    const link = await screen.findByRole('link', { name: 'Rechnungen' });
    expect(link).toHaveAttribute('href', '/invoices?property_id=p1');
    fireEvent.click(link);
    expect(await screen.findByText('RE-a')).toBeInTheDocument();
    expect(screen.queryByText('RE-b')).not.toBeInTheDocument();
    const open = screen.getByRole('button', { name: 'Offen: Quellvorgänge anzeigen' });
    expect(open).toHaveTextContent('10,00');
    fireEvent.click(open);
    expect(currentParams().get('property_id')).toBe('p1');
    expect(currentParams().get('status')).toBe('unpaid');
  });

  it('clears only the visible object filter, preserving status and unrelated URL parameters', async () => {
    state.invoices = [invoice('a', 'p1', 'paid', 10), invoice('b', 'p2', 'paid', 99), invoice('c', 'p1', 'open', 7)];
    show('/invoices?property_id=p1&status=paid&origin=dossier');
    await screen.findByText('RE-a');
    expect(screen.queryByText('RE-b')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Immobilienfilter entfernen' }));
    expect(await screen.findByText('RE-b')).toBeInTheDocument();
    expect(screen.queryByText('RE-c')).not.toBeInTheDocument();
    expect(currentParams().has('property_id')).toBe(false);
    expect(currentParams().get('status')).toBe('paid');
    expect(currentParams().get('origin')).toBe('dossier');
    expect(screen.queryByRole('button', { name: 'Immobilienfilter entfernen' })).not.toBeInTheDocument();
  });

  it('restores and saves object IDs in named invoice views while retaining unrelated URL state', async () => {
    state.invoices = [invoice('a', 'p1', 'paid', 10), invoice('b', 'p2', 'paid', 99)];
    state.views = [{ id: 'house-b', name: 'Haus B bezahlt', revision: 1,
      config: { column_filters: { property_id: 'p2', workflow_filter: 'paid' } } }];
    show('/invoices?property_id=p1&origin=dossier');
    await screen.findByRole('option', { name: 'Haus B bezahlt' });
    fireEvent.change(screen.getByRole('combobox', { name: 'Ansicht' }), { target: { value: 'house-b' } });
    expect(await screen.findByText('RE-b')).toBeInTheDocument();
    expect(screen.queryByText('RE-a')).not.toBeInTheDocument();
    expect(currentParams().get('property_id')).toBe('p2');
    expect(currentParams().get('status')).toBe('paid');
    expect(currentParams().get('origin')).toBe('dossier');
    fireEvent.change(screen.getByLabelText('Name der neuen Ansicht'), { target: { value: 'Objekt B' } });
    fireEvent.click(screen.getByRole('button', { name: 'Ansicht speichern' }));
    await waitFor(() => expect(workspace.put).toHaveBeenCalledWith('views', expect.any(String), expect.objectContaining({
      name: 'Objekt B', config: expect.objectContaining({ column_filters: expect.objectContaining({ property_id: 'p2', workflow_filter: 'paid' }) }),
    })));
  });

  it('keeps an unknown object ID explicit instead of silently showing all invoices', async () => {
    state.invoices = [invoice('a', 'p1', 'open', 10)];
    show('/invoices?property_id=missing');
    expect(await screen.findByText(/Unbekannte Immobilie \(missing\)/)).toBeInTheDocument();
    expect(screen.queryByText('RE-a')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Immobilienfilter entfernen' }));
    expect(await screen.findByText('RE-a')).toBeInTheDocument();
  });

  async function newInvoice() {
    show(); await screen.findByRole('button', { name: 'Neu' });
    fireEvent.click(screen.getByRole('button', { name: 'Neu' }));
    const form = await screen.findByRole('dialog', { name: 'Rechnung erstellen' });
    await waitFor(() => expect(within(form).getByRole('button', { name: 'Speichern', exact: true })).not.toBeDisabled());
    fireEvent.change(within(form).getByLabelText('Lieferant *'), { target: { value: 'Testlieferant' } });
    fireEvent.change(within(form).getByLabelText('Rechnungsdatum *'), { target: { value: '2026-10-01' } });
    fireEvent.change(within(form).getByLabelText('Netto (€) *'), { target: { value: '100' } });
    return form;
  }

  it('uses residuals instead of full invoice amounts and exposes missing payment evidence', async () => {
    state.invoices = [
      { ...invoice('part', 'p1', 'open', 120), payment_summary: { status: 'overdue', paid: 20, open: 100, overdue: true, due_on: '2000-01-01' } },
      { ...invoice('manual', 'p1', 'paid', 90), payment_summary: { status: 'paid', paid: 0, open: null,
        overdue: false, note: 'Manueller Zahlungsstatus ohne zugeordnete Zahlung' } },
    ];
    show();
    await screen.findByText('RE-part');
    expect(screen.getByRole('button', { name: 'Offen: Quellvorgänge anzeigen' })).toHaveTextContent('100,00');
    expect(screen.getByRole('button', { name: 'Überfällig: Quellvorgänge anzeigen' })).toHaveTextContent('100,00');
    expect(screen.getByRole('button', { name: 'Bezahlt: Quellvorgänge anzeigen' })).toHaveTextContent('20,00');
    expect(screen.getByRole('button', { name: 'Zahlungsstand ungeklärt: Quellvorgänge anzeigen' })).toHaveTextContent('1');
    fireEvent.click(screen.getByRole('button', { name: 'Bezahlt: Quellvorgänge anzeigen' }));
    expect(screen.getByText('RE-part')).toBeInTheDocument();
    expect(screen.queryByText('RE-manual')).not.toBeInTheDocument();
    expect(api.patch).not.toHaveBeenCalled();
  });

  it('uses an explicitly configured default VAT rate of zero and fills only a missing VAT amount', async () => {
    state.taxRates = [{ id: 'zero', name: 'Steuerfrei', rate: 0, is_default: true }, { id: 'regular', name: 'Regel', rate: 19 }];
    const form = await newInvoice();
    expect(within(form).getByLabelText('MwSt-Satz (%)')).toHaveValue('0');
    fireEvent.change(within(form).getByLabelText('Brutto (€) *'), { target: { value: '100' } });
    fireEvent.submit(form.querySelector('form'));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/invoices', expect.objectContaining({ vat_rate: '0', vat_amount: 0, gross_amount: 100 })));
  });

  it('preserves explicitly entered zero VAT and gross amounts rather than recalculating them', async () => {
    const form = await newInvoice();
    fireEvent.change(within(form).getByLabelText('MwSt-Betrag (€)'), { target: { value: '0' } });
    fireEvent.change(within(form).getByLabelText('Brutto (€) *'), { target: { value: '0' } });
    fireEvent.submit(form.querySelector('form'));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/invoices', expect.objectContaining({ net_amount: 100, vat_amount: 0, gross_amount: 0 })));
  });

  it('still calculates a missing VAT amount without replacing an entered gross amount', async () => {
    const form = await newInvoice();
    fireEvent.change(within(form).getByLabelText('Brutto (€) *'), { target: { value: '119' } });
    fireEvent.submit(form.querySelector('form'));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/invoices', expect.objectContaining({ vat_amount: 19, gross_amount: 119 })));
  });
});

describe('dossier rent completeness and report entrances', () => {
  it('labels a partial rent subtotal and withholds annual and per-area figures despite complete areas', async () => {
    state.units = [unit('u1', 500.10), unit('u2', null)];
    show('/properties/p1?tab=finance');
    await screen.findByRole('heading', { name: 'Gleiches Haus' });
    expect(stat(/Monatliche Plan-Kaltmiete \(unvollständige Zwischensumme\)/)).toHaveTextContent('500,10');
    expect(stat(/Jährliche Plan-Kaltmiete/)).toHaveTextContent('—');
    expect(stat(/Plan-Kaltmiete Ø/)).toHaveTextContent('—');
    expect(screen.getByText(/Für 1 von 2 Einheiten fehlt die Plan-Kaltmiete/)).toBeInTheDocument();
    const sources = screen.getByRole('region', { name: 'Planmieten nach Einheit' });
    const row = within(sources).getByRole('row', { name: /Einheit u2/ });
    expect(within(row).getAllByRole('cell')[2]).toHaveTextContent('—');
    expect(within(row).getAllByRole('cell')[5]).toHaveTextContent('0,00 € (unvollständig)');
    expect(within(sources).getAllByText('500,10 € (unvollständig)')).toHaveLength(2);
    expect(screen.getByRole('link', { name: 'Auswertungen dieses Objekts' })).toHaveAttribute('href', '/reports?kind=cash-v2&property_id=p1');
  });

  it('keeps an entirely missing rent basis blank rather than manufacturing a zero subtotal', async () => {
    state.units = [unit('u1', null, { service_charge_advance: null, heating_advance: null })];
    show('/properties/p1?tab=finance');
    await screen.findByRole('heading', { name: 'Gleiches Haus' });
    expect(stat(/Monatliche Plan-Kaltmiete/)).toHaveTextContent('—');
    expect(stat(/Jährliche Plan-Kaltmiete/)).toHaveTextContent('—');
    expect(stat(/Plan-Kaltmiete Ø/)).toHaveTextContent('—');
  });

  it('sums cents and accepts genuine zero rents as a complete annual and area basis', async () => {
    state.units = [unit('u1', 0.10), unit('u2', 0.20), unit('u3', 0)];
    show('/properties/p1?tab=finance');
    await screen.findByRole('heading', { name: 'Gleiches Haus' });
    expect(stat(/Monatliche Plan-Kaltmiete/)).toHaveTextContent('0,30');
    expect(stat(/Jährliche Plan-Kaltmiete/)).toHaveTextContent('3,60');
    expect(stat(/Plan-Kaltmiete Ø/)).toHaveTextContent('0,00');
    expect(screen.queryByText(/unvollständige Zwischensumme/)).not.toBeInTheDocument();
  });

  it.each([0, null])('distinguishes zero and missing unit heating advances and contract deposits (%s)', async amount => {
    state.units = [unit('u1', 0, { heating_advance: amount })];
    state.contracts = [{ id: 'c1', unit_id: 'u1', property_id: 'p1', status: 'active', start_date: '2020-01-01', contract_number: 'MV-1', deposit_amount: amount }];
    show('/units/u1'); await screen.findByRole('heading', { name: 'Einheit u1' });
    expect(screen.getByText('Plan-Heizkosten').nextElementSibling).toHaveTextContent(amount === 0 ? '0,00' : '—');
    expect(screen.getByText('Kaution').nextElementSibling).toHaveTextContent(amount === 0 ? '0,00' : '—');
    expect(screen.getByRole('link', { name: 'Auswertungen dieser Einheit' })).toHaveAttribute('href', '/reports?kind=cash-v2&property_id=p1&unit_id=u1');
  });
});
