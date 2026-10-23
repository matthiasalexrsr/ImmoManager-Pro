import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import useLookupChoices from '../hooks/useLookupChoices';
import ServiceContracts from '../pages/ServiceContracts';
import ServiceContractDetail from '../pages/ServiceContractDetail';
import InvoiceReview from '../pages/InvoiceReview';
import InvoiceReviewDetail from '../pages/InvoiceReviewDetail';
import Dunning from '../pages/Dunning';
import { api } from '../api';
import { de } from '../features/invoiceReview/text';

vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() } }));
vi.mock('../i18n', () => {
  const t = key => key;
  return { useTranslation: () => ({ t, locale: 'de-DE' }) };
});
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => true, useAuth: () => null }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => async () => true }));
vi.mock('../components/NotificationArrival', () => ({ default: () => null }));
vi.mock('../components/PdfPreview', () => ({ default: () => null }));
vi.mock('../components/FileViewer', () => ({ default: () => null }));
vi.mock('../components/FormModal', () => ({ default: ({ title }) => <div role="dialog">{title}</div> }));
vi.mock('../components/DataTable', () => ({ default: ({ data, onAdd }) => <section aria-label="Vertragsliste">
  {onAdd && <button onClick={onAdd}>Neu</button>}{data.map(row => <span key={row.id}>{row.title}</span>)}
</section> }));
vi.mock('../features/invoiceReview/ReviewPanels', () => ({
  Summary: () => <p>Rechnungsakte sichtbar</p>, ReceiptForm: () => <form aria-label="Rechnungseingang" />,
  Checks: () => null, Decision: () => null, Dispute: () => null, Findings: () => null,
  History: () => null, Payment: () => null, Transfer: () => null,
}));
vi.mock('../features/dunning/DunningTabs', () => ({
  CasesTab: () => <p>Mahnakten sichtbar</p>, OutboxTab: () => null, RepliesTab: () => null, SettingsTab: () => null,
  RunTab: ({ portfolios }) => <form aria-label="Mahnlauf vorbereiten">{portfolios.map(row => <span key={row.id}>{row.name}</span>)}</form>,
}));

const contract = { id: 's1', title: 'Objektvertrag A', provider_name: 'Versorger', status: 'active', locations: [], tariffs: [], terms: {}, restricted: false };
const invoice = { invoice: { id: 'i1', supplier: 'Lieferant A', gross_amount: 119 }, review: null,
  abilities: { receive: true }, assignment: {}, kind: 'invoice', status: 'legacy' };

function deferred() {
  let resolve;
  const promise = new Promise(yes => { resolve = yes; });
  return { promise, resolve };
}
function show(Page, path, route = path) {
  return render(<MemoryRouter initialEntries={[path]}><Routes><Route path={route} element={<Page />} /></Routes></MemoryRouter>);
}
beforeEach(() => {
  vi.resetAllMocks();
  api.list.mockResolvedValue([]);
  api.get.mockImplementation(path => Promise.resolve(path.startsWith('/service-contracts/deadlines') ? []
    : path.startsWith('/service-contracts/') ? contract
      : path === '/invoices/i1/review' ? invoice : { items: [{ invoice_id: 'i1', supplier: 'Lieferant A', invoice_date: '2026-10-01', gross_amount: 119 }], total: 1, has_more: false }));
});
afterEach(cleanup);

describe('validated lookup collections', () => {
  it.each([null, {}, { items: [] }])('keeps malformed %j sources unavailable and accepts valid empty collections on retry', async value => {
    api.list.mockResolvedValueOnce(value).mockResolvedValueOnce([]);
    const { result } = renderHook(() => useLookupChoices({ properties: '/properties' }));
    await waitFor(() => expect(result.current.error).toContain('nicht vollständig'));
    expect(result.current.ready).toBe(false);
    act(() => result.current.reload());
    await waitFor(() => expect(result.current.ready).toBe(true));
    expect(result.current.data.properties).toEqual([]);
  });

  it('requires every source and identifies a rejected auxiliary collection', async () => {
    api.list.mockImplementation(path => path === '/meters' ? Promise.reject(new Error('Zählerserver offline')) : Promise.resolve([]));
    const { result } = renderHook(() => useLookupChoices({ contacts: '/contacts', properties: '/properties', units: '/units', meters: '/meters' }));
    await waitFor(() => expect(result.current.error).toContain('Zählerserver offline'));
    expect(result.current.ready).toBe(false);
  });

  it('aborts previous scopes and rejects their late results after reopening another record', async () => {
    const older = deferred(), newer = deferred();
    api.list.mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);
    const { result, rerender, unmount } = renderHook(({ enabled, scope }) => useLookupChoices({ contacts: '/contacts' }, enabled, scope),
      { initialProps: { enabled: true, scope: 'a' } });
    const firstSignal = api.list.mock.calls[0][1].signal;
    rerender({ enabled: false, scope: 'a' });
    expect(firstSignal.aborted).toBe(true);
    rerender({ enabled: true, scope: 'b' });
    await act(async () => newer.resolve([{ id: 'new' }]));
    await waitFor(() => expect(result.current.ready).toBe(true));
    await act(async () => older.resolve([{ id: 'old' }]));
    expect(result.current.data.contacts).toEqual([{ id: 'new' }]);
    unmount();
    expect(api.list.mock.calls[1][1].signal.aborted).toBe(true);
  });

  it('fences overlapping retries without allowing an older successful array to win', async () => {
    const older = deferred(), newer = deferred();
    api.list.mockRejectedValueOnce(new Error('Offline')).mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);
    const { result } = renderHook(() => useLookupChoices({ properties: '/properties' }));
    await waitFor(() => expect(result.current.error).toContain('Offline'));
    act(() => result.current.reload());
    act(() => result.current.reload());
    await act(async () => newer.resolve([{ id: 'new' }]));
    await act(async () => older.resolve([{ id: 'old' }]));
    expect(result.current.ready).toBe(true);
    expect(result.current.data.properties).toEqual([{ id: 'new' }]);
  });
});

it('retains the service list while failed creation choices block a blank form and recover on retry', async () => {
  let fail = true;
  api.list.mockImplementation(path => path.startsWith('/service-contracts') ? Promise.resolve([contract])
    : fail && path === '/contacts' ? Promise.reject(new Error('Kontaktquelle offline')) : Promise.resolve([]));
  show(ServiceContracts, '/service-contracts');
  fireEvent.click(await screen.findByRole('button', { name: 'Neu' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Kontaktquelle offline');
  expect(screen.getByText('Objektvertrag A')).toBeInTheDocument();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  fail = false;
  fireEvent.click(screen.getByRole('button', { name: 'Auswahl erneut laden' }));
  expect(await screen.findByRole('dialog')).toHaveTextContent('serviceContracts.create');
});

it('does not allow a late service filter response to replace the current selection', async () => {
  const older = deferred(), newer = deferred();
  api.list.mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);
  show(ServiceContracts, '/service-contracts');
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'aktuell' } });
  await waitFor(() => expect(api.list).toHaveBeenCalledTimes(2));
  expect(api.list.mock.calls[0][1].signal.aborted).toBe(true);
  await act(async () => newer.resolve([{ ...contract, title: 'Aktuelle Auswahl' }]));
  await screen.findByText('Aktuelle Auswahl');
  await act(async () => older.resolve([contract]));
  expect(screen.queryByText('Objektvertrag A')).not.toBeInTheDocument();
});

it('preserves a contract dossier while failed editing contacts block its write form', async () => {
  api.list.mockRejectedValueOnce(new Error('Kontakte offline')).mockResolvedValueOnce([]);
  show(ServiceContractDetail, '/service-contracts/s1', '/service-contracts/:id');
  fireEvent.click(await screen.findByRole('button', { name: 'serviceContracts.edit' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Kontakte offline');
  expect(screen.getByRole('heading', { name: 'Objektvertrag A' })).toBeInTheDocument();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Auswahl erneut laden' }));
  expect(await screen.findByRole('dialog')).toHaveTextContent('serviceContracts.editContract');
});

it('keeps the invoice inbox available while failed property choices disable new receipts and filters', async () => {
  api.list.mockRejectedValueOnce(new Error('Immobilien offline')).mockResolvedValueOnce([]);
  show(InvoiceReview, '/invoice-review');
  expect(await screen.findByRole('alert')).toHaveTextContent('Immobilien offline');
  expect(screen.getByText('Lieferant A')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: de.newInvoice })).toBeDisabled();
  expect(screen.getByRole('combobox', { name: de.property })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Auswahl erneut laden' }));
  await waitFor(() => expect(screen.getByRole('button', { name: de.newInvoice })).toBeEnabled());
});

it('keeps a legacy invoice visible while its receipt waits for verified property choices', async () => {
  api.list.mockRejectedValueOnce(new Error('Immobilien offline')).mockResolvedValueOnce([]);
  show(InvoiceReviewDetail, '/invoice-review/i1', '/invoice-review/:id');
  expect(await screen.findByRole('alert')).toHaveTextContent('Immobilien offline');
  expect(screen.getByText('Rechnungsakte sichtbar')).toBeInTheDocument();
  expect(screen.queryByRole('form', { name: 'Rechnungseingang' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Auswahl erneut laden' }));
  expect(await screen.findByRole('form', { name: 'Rechnungseingang' })).toBeInTheDocument();
});

it('never mounts a dunning run against failed portfolio choices, while keeping cases visible', async () => {
  api.list.mockRejectedValueOnce(new Error('Portfolios offline')).mockResolvedValueOnce([{ id: 'p1', name: 'Freigegebener Bestand' }]);
  show(Dunning, '/dunning');
  expect(await screen.findByRole('alert')).toHaveTextContent('Portfolios offline');
  expect(screen.getByText('Mahnakten sichtbar')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('tab', { name: 'Mahnlauf' }));
  expect(screen.queryByRole('form')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Auswahl erneut laden' }));
  expect(await screen.findByRole('form', { name: 'Mahnlauf vorbereiten' })).toHaveTextContent('Freigegebener Bestand');
});
