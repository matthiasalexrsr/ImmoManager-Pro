import { createElement } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import Receivables from '../pages/Receivables';
import Invoices from '../pages/Invoices';
import AllocationKeys from '../pages/AllocationKeys';
import { api } from '../api';
vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), captureSession: () => () => {} } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key, locale: 'de-DE' }) }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => false, useAuth: () => null }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => ({ invalidateRelated: vi.fn() }), useEntities: key => ({ loading: false, error: null,
  items: key === 'contracts' ? [{ id: 'c1', property_id: 'p1', unit_id: 'u1', tenant_id: 't1', contract_number: 'MV-1' }]
    : key === 'tenants' ? [{ id: 't1', full_name: 'Lena Weiß' }] : [] }) }));
vi.mock('../hooks/useEffectiveSettings', () => ({ default: () => ({ prefs: {} }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => vi.fn() }));
vi.mock('../components/Toast', () => ({ useToast: () => ({ error: vi.fn(), success: vi.fn() }) }));
vi.mock('../features/ReceivableSettlement', () => ({ default: () => <span>Abrechnung geprüft</span> }));
vi.mock('../features/aktenwerk/aktenwerkApi', () => ({ useAktenwerkReady: () => false, aktenwerkBulkAction: () => null, documentExchangeId: () => '' }));
const claim = { id: 'r1', description: 'Ausgewählte Mietforderung', amount_due: 100, status: 'paid', due_date: '2026-01-01', contract_id: 'c1', statement_id: 'statement-1' };
const invoice = { id: 'i1', supplier: 'Ausgewählte Versorgerrechnung', invoice_number: 'RE-1', gross_amount: 100,
  property_id: 'p1', status: 'paid', invoice_date: '2026-01-01', payment_summary: { paid: 100, open: 0, status: 'paid', overdue: false } };
beforeEach(() => {
  vi.resetAllMocks(); localStorage.clear();
  api.list.mockImplementation(async path => path === '/receivables' ? [claim] : path === '/invoices/overview' ? [invoice] : []);
  api.get.mockResolvedValue({});
});
afterEach(cleanup);
it('opens an exact receivable even when status, statement and object filters describe other records', async () => {
  render(<MemoryRouter initialEntries={['/receivables?focus_id=r1&statement_id=other&status=credits&property_id=other&date_from=2027-01-01']}><Receivables /></MemoryRouter>);
  expect(await screen.findByText('Ausgewählte Mietforderung')).toBeVisible();
  expect(api.list).toHaveBeenCalledWith('/receivables', expect.anything());
});
it('opens an exact invoice even when its status and property conflict with the list filters', async () => {
  render(<MemoryRouter initialEntries={['/invoices?focus_id=i1&status=unpaid&property_id=other']}><Invoices /></MemoryRouter>);
  expect(await screen.findByRole('link', { name: 'Ausgewählte Versorgerrechnung' })).toBeVisible();
});

function RouteProbe() {
  const location = useLocation(); const navigate = useNavigate();
  return <><output aria-label="Aktuelle URL">{location.search}</output><button onClick={() => navigate(-1)}>Zurück zur Quelle</button></>;
}
it.each([
  { Page: Receivables, route: '/receivables', label: 'Offene Forderungen', row: 'Ausgewählte Mietforderung' },
  { Page: Invoices, route: '/invoices', label: 'Unbezahlt', row: 'Ausgewählte Versorgerrechnung' },
])('lets explicit filters leave a $route source and Back restores its entry', async ({ Page, route, label, row }) => {
  render(<MemoryRouter initialEntries={[`${route}?focus_id=${route === '/invoices' ? 'i1' : 'r1'}&notice_id=n1&source_id=s1`]}>{createElement(Page)}<RouteProbe /></MemoryRouter>);
  expect(await screen.findByText(row)).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: label, exact: true }));
  expect(screen.getByLabelText('Aktuelle URL')).toHaveTextContent('?status=unpaid');
  expect(screen.getByLabelText('Aktuelle URL')).not.toHaveTextContent('focus_id');
  fireEvent.click(screen.getByRole('button', { name: 'Zurück zur Quelle' }));
  expect(await screen.findByText(row)).toBeVisible();
  expect(screen.getByLabelText('Aktuelle URL')).toHaveTextContent('focus_id=');
});
it.each([{ Page: Invoices, route: 'invoices', label: 'Rechnung' }, { Page: Receivables, route: 'receivables', label: 'Forderung' }])('reports an unavailable exact $route source', async ({ Page, route, label }) => {
  render(<MemoryRouter initialEntries={[`/${route}?focus_id=removed`]}>{createElement(Page)}</MemoryRouter>);
  expect(await screen.findByRole('alert')).toHaveTextContent(new RegExp(`${label}.*nicht mehr vorhanden|${label}.*nicht verfügbar|${label}.*entfernt`));
});
it('preserves the billing property context in allocation-key links and can explicitly leave it', async () => {
  api.list.mockImplementation(async path => path === '/billing/allocation-keys' ? [
    { id: 'k1', property_id: 'p1', name: 'Fläche Stuttgart', key_type: 'area_sqm' },
    { id: 'k2', property_id: 'p2', name: 'Fläche Tübingen', key_type: 'area_sqm' },
  ] : []);
  render(<MemoryRouter initialEntries={['/allocation-keys?property_id=p1']}><AllocationKeys /></MemoryRouter>);
  expect(await screen.findByText('Fläche Stuttgart')).toBeVisible();
  expect(screen.queryByText('Fläche Tübingen')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Alle Immobilien anzeigen' }));
  expect(await screen.findByText('Fläche Tübingen')).toBeVisible();
});
