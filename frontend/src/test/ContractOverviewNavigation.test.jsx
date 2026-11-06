import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import Contracts from '../pages/Contracts';
import { api } from '../api';

const state = vi.hoisted(() => ({ canWrite: true, listFails: false, detail: null, actorId: 'owner-1' }));
vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), captureSession: () => () => {} } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: () => undefined, locale: 'de-DE' }) }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => state.canWrite, useAuth: () => ({ user: { id: state.actorId } }) }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => null, useEntities: key => ({ loading: false, error: null,
  items: key === 'properties' ? [{ id: 'p1', name: 'Haus am Park' }] : key === 'units' ? [{ id: 'u1', label: 'Wohnung 3' }]
    : key === 'tenants_all' ? [{ id: 't1', full_name: 'Leonie Weber' }] : [] }) }));
vi.mock('../components/Toast', () => ({ useToast: () => ({ error: vi.fn(), success: vi.fn() }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => vi.fn() }));
vi.mock('../features/partyWorkspace/PartyWorkspace', () => ({ PartyLink: ({ children }) => <button>{children}</button> }));
vi.mock('../features/communication/QuickMessageComposer', () => ({ default: props => <div role="dialog" aria-label="Nachricht">{props.sourceId}<button onClick={props.onClose}>Schließen</button></div> }));
vi.mock('../features/communication/ReminderPlanner', () => ({ default: props => <div role="dialog" aria-label="Erinnerung">{props.sourceId}<button onClick={props.onClose}>Schließen</button></div> }));

const contract = { id: 'c1', contract_number: 'MV-2026-001', property_id: 'p1', unit_id: 'u1', tenant_id: 't1',
  start_date: '2026-01-01', end_date: '2026-12-31', status: 'active', deposit_amount: 2100, index_rent: 'fixed', notice_period: '3 Monate' };
beforeEach(() => {
  vi.resetAllMocks(); localStorage.clear(); state.canWrite = true; state.listFails = false; state.actorId = 'owner-1'; state.detail = { ...contract };
  api.list.mockImplementation(async path => { if (path === '/contracts' && state.listFails) throw new Error('Liste offline'); return []; });
  api.get.mockImplementation(async path => {
    if (path === '/contracts/current-rents') return {};
    if (path === '/contracts/c1') return state.detail;
    throw new Error(`Unexpected detail ${path}`);
  });
});
afterEach(cleanup);
function Navigation() { const location = useLocation(); const navigate = useNavigate(); return <>
  <output aria-label="Route">{location.search}</output><button onClick={() => navigate(-1)}>Zurück</button>
  <button onClick={() => navigate('/contracts?focus_id=c2')}>Anderen Vertrag öffnen</button>
  <Contracts />
</>; }
function mount(query) { return render(<MemoryRouter initialEntries={['/contracts' + query]}><Navigation /></MemoryRouter>); }

describe('contract overview direct navigation', () => {
  it.each(['focus_id', 'contract_id'])('resolves %s despite an incompatible list context and empty list', async parameter => {
    mount(`?property_id=other&filter=terminated&${parameter}=c1`);
    const overview = await screen.findByRole('region', { name: contract.contract_number });
    expect(api.get).toHaveBeenCalledWith('/contracts/c1', expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(within(overview).getByRole('link', { name: 'Haus am Park' })).toHaveAttribute('href', '/properties/p1');
    expect(within(overview).getByRole('link', { name: 'Aufgaben zur Einheit' })).toHaveAttribute('href', '/tasks?property_id=p1&unit_id=u1');
    expect(within(overview).getByText('31.12.2026')).toBeVisible();
    await waitFor(() => expect(screen.getByRole('heading', { name: contract.contract_number })).toHaveFocus());
  });
  it('opens the authoritative record even when the list fails', async () => {
    state.listFails = true; mount('?focus_id=c1');
    expect(await screen.findByRole('heading', { name: contract.contract_number })).toBeVisible();
    expect(screen.getByText(/Liste offline/)).toBeVisible();
  });
  it.each([403, 404])('shows a source-unavailable state without showing stale data for HTTP %s', async code => {
    const previous = api.get.getMockImplementation();
    api.get.mockImplementation(path => path === '/contracts/c1' ? Promise.reject(Object.assign(new Error('private detail'), { statusCode: code })) : previous(path));
    mount('?focus_id=c1');
    expect(await screen.findByText('Vertrag nicht verfügbar')).toBeVisible();
    expect(screen.queryByText('private detail')).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: contract.contract_number })).not.toBeInTheDocument();
  });
  it('retries a failed detail independently of the successful list', async () => {
    const previous = api.get.getMockImplementation(); let failed = false;
    api.get.mockImplementation(path => { if (path === '/contracts/c1' && !failed) { failed = true; return Promise.reject(new Error('Verbindung unterbrochen')); } return previous(path); });
    mount('?contract_id=c1'); await screen.findByText('Vertrag konnte nicht geladen werden');
    fireEvent.click(screen.getByRole('button', { name: 'Vertrag erneut laden' }));
    expect(await screen.findByRole('heading', { name: contract.contract_number })).toBeVisible();
  });
  it('keeps filters, clears notification context on close and reopens with Back', async () => {
    mount('?property_id=other&filter=terminated&focus_id=c1&source_id=c1&notice_id=n1');
    await screen.findByRole('heading', { name: contract.contract_number });
    fireEvent.click(screen.getByRole('button', { name: 'Vertragsübersicht schließen' }));
    expect(screen.getByLabelText('Route')).toHaveTextContent('?property_id=other&filter=terminated');
    expect(screen.queryByRole('heading', { name: contract.contract_number })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Zurück' }));
    expect(await screen.findByRole('heading', { name: contract.contract_number })).toBeVisible();
  });
  it('discards an old response after a second contract is selected', async () => {
    let resolveFirst; const previous = api.get.getMockImplementation();
    api.get.mockImplementation(path => path === '/contracts/c1' ? new Promise(resolve => { resolveFirst = resolve; })
      : path === '/contracts/c2' ? Promise.resolve({ ...contract, id: 'c2', contract_number: 'MV-2026-002' }) : previous(path));
    mount('?focus_id=c1'); await screen.findByText('Vertrag wird geladen …');
    fireEvent.click(screen.getByRole('button', { name: 'Anderen Vertrag öffnen' }));
    await screen.findByRole('heading', { name: 'MV-2026-002' });
    await act(async () => resolveFirst(contract));
    expect(screen.queryByRole('heading', { name: contract.contract_number })).not.toBeInTheDocument();
  });
  it('keeps the overview readable for a readonly role and opens source-bound personal actions', async () => {
    state.canWrite = false; mount('?focus_id=c1');
    const overview = await screen.findByRole('region', { name: contract.contract_number });
    expect(within(overview).queryByRole('button', { name: 'Vertrag bearbeiten' })).not.toBeInTheDocument();
    fireEvent.click(within(overview).getByRole('button', { name: 'Nachricht schreiben' }));
    expect(screen.getByRole('dialog', { name: 'Nachricht' })).toHaveTextContent('c1');
    fireEvent.click(screen.getByRole('button', { name: 'Schließen' }));
    fireEvent.click(within(overview).getByRole('button', { name: 'Erinnerung einstellen' }));
    expect(screen.getByRole('dialog', { name: 'Erinnerung' })).toHaveTextContent('c1');
  });
});

it('includes contracts ending today in the deadline total and list without negative remaining-day labels', async () => {
  const day = offset => { const date = new Date(); date.setDate(date.getDate() + offset); return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`; };
  api.list.mockImplementation(async path => path === '/contracts' ? [
    { ...contract, id: 'today', contract_number: 'Endet heute', end_date: day(0) },
    { ...contract, id: 'past', contract_number: 'Bereits beendet', end_date: day(-1) },
    { ...contract, id: 'future', contract_number: 'Endet später', end_date: day(90) },
  ] : []);
  mount('');
  await screen.findByRole('link', { name: 'Endet heute' });
  expect(screen.getAllByTitle('endet heute').length).toBeGreaterThan(0);
  expect(screen.queryByTitle(/noch -/)).not.toBeInTheDocument();
  const count = screen.getByRole('button', { name: /Endet.*90.*Quellvorgänge anzeigen/ });
  expect(count.querySelector('.kpi-value')).toHaveTextContent('2');
  fireEvent.click(count);
  expect(screen.getByRole('link', { name: 'Endet heute' })).toBeVisible();
  expect(screen.getByRole('link', { name: 'Endet später' })).toBeVisible();
  expect(screen.queryByRole('link', { name: 'Bereits beendet' })).not.toBeInTheDocument();
});

it('hides an already loaded contract immediately on the same route when the account changes', async () => {
  const view = mount('?focus_id=c1');
  await screen.findByRole('heading', { name: contract.contract_number });
  const previous = api.get.getMockImplementation();
  api.get.mockImplementation(path => path === '/contracts/c1' ? Promise.reject(Object.assign(new Error('private detail'), { statusCode: 403 })) : previous(path));
  state.actorId = 'owner-2';
  view.rerender(<MemoryRouter initialEntries={['/contracts?focus_id=c1']}><Navigation /></MemoryRouter>);
  expect(screen.queryByRole('heading', { name: contract.contract_number })).not.toBeInTheDocument();
  expect(await screen.findByText('Vertrag nicht verfügbar')).toBeVisible();
  expect(screen.queryByText('private detail')).not.toBeInTheDocument();
});
it('discards an old account response even when the requested contract ID stays the same', async () => {
  let finishOld; let finishNew; const previous = api.get.getMockImplementation(); let requests = 0;
  api.get.mockImplementation(path => path === '/contracts/c1' ? new Promise(resolve => { if (++requests === 1) finishOld = resolve; else finishNew = resolve; }) : previous(path));
  const view = mount('?focus_id=c1');
  await screen.findByText('Vertrag wird geladen …');
  state.actorId = 'owner-2';
  view.rerender(<MemoryRouter initialEntries={['/contracts?focus_id=c1']}><Navigation /></MemoryRouter>);
  await act(async () => finishNew({ ...contract, contract_number: 'Vertrag des aktuellen Kontos' }));
  await screen.findByRole('heading', { name: 'Vertrag des aktuellen Kontos' });
  await act(async () => finishOld(contract));
  expect(screen.queryByRole('heading', { name: contract.contract_number })).not.toBeInTheDocument();
});
it.each(['workspace-owner', 'workspace-logout'])('removes loaded details on %s before the auth context updates and can retry explicitly', async event => {
  mount('?focus_id=c1');
  await screen.findByRole('heading', { name: contract.contract_number });
  act(() => window.dispatchEvent(new Event(event)));
  expect(screen.queryByRole('heading', { name: contract.contract_number })).not.toBeInTheDocument();
  expect(screen.getByText('Die Sitzung wurde geändert. Bitte den Vertrag erneut laden.')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Vertrag erneut laden' }));
  expect(await screen.findByRole('heading', { name: contract.contract_number })).toBeVisible();
});

it('turns a synchronous session capture failure into a recoverable contract state before issuing a detail request', async () => {
  const capture = vi.spyOn(api, 'captureSession').mockImplementationOnce(() => { throw Object.assign(new Error('Sitzung geändert'), { code: 'SESSION_CHANGED' }); });
  try {
    mount('?focus_id=c1');
    expect(await screen.findByText('Vertrag konnte nicht geladen werden')).toBeVisible();
    expect(screen.getByText('Sitzung geändert')).toBeVisible();
    expect(api.get).not.toHaveBeenCalledWith('/contracts/c1', expect.anything());
    capture.mockRestore();
    fireEvent.click(screen.getByRole('button', { name: 'Vertrag erneut laden' }));
    expect(await screen.findByRole('heading', { name: contract.contract_number })).toBeVisible();
  } finally { capture.mockRestore(); }
});
