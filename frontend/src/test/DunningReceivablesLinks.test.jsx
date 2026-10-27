import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter, useLocation } from 'react-router-dom';
import Receivables from '../pages/Receivables';
import { api } from '../api';

const fixture = vi.hoisted(() => ({
  locale: 'de-DE',
  contracts: [
    { id: 'k1', contract_number: 'MV-A', tenant_id: 't1', property_id: 'p1', unit_id: 'u1' },
    { id: 'k2', contract_number: 'MV-B', tenant_id: 't2', property_id: 'p1', unit_id: 'u2' },
  ],
  tenants: [{ id: 't1', full_name: 'Anna Beispiel' }, { id: 't2', full_name: 'Berta Beispiel' }],
}));
vi.mock('../api', () => ({ api: {
  list: vi.fn(), get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), captureSession: vi.fn(() => () => {}),
} }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key, locale: fixture.locale }) }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => null, useCanWrite: () => false }));
vi.mock('../contexts/DataStoreContext', () => ({
  useDataStore: () => ({ invalidateRelated: vi.fn() }),
  useEntities: key => ({ items: key === 'contracts' ? fixture.contracts : key === 'tenants' ? fixture.tenants : [],
    loading: false, error: null }),
}));
vi.mock('../hooks/useEffectiveSettings', () => ({ default: () => ({ prefs: null, error: null }) }));
vi.mock('../features/ReceivableSettlement', () => ({ default: () => <span>Saldo</span> }));
vi.mock('../features/partyWorkspace/PartyWorkspace', () => ({
  PartyLink: ({ children }) => <span>{children}</span>,
}));

function CurrentRoute() {
  const location = useLocation();
  return <span data-testid="receivables-route">{location.pathname + location.search}</span>;
}
function show(path = '/receivables') {
  return render(<MemoryRouter initialEntries={[path]}><CurrentRoute /><Receivables /></MemoryRouter>);
}
beforeEach(() => {
  vi.clearAllMocks(); fixture.locale = 'de-DE'; localStorage.clear(); sessionStorage.clear();
  api.list.mockResolvedValue([
    { id: 'r1', contract_id: 'k1', amount_due: 250, status: 'overdue', dunning_level: '2', due_date: '2026-09-01', description: 'Rückstand A' },
    { id: 'r2', contract_id: 'k2', amount_due: 90, status: 'open', dunning_level: null, due_date: '2026-09-02', description: 'Rückstand B' },
    { id: 'r3', contract_id: 'missing', amount_due: 10, status: 'overdue', dunning_level: '1', due_date: '2026-09-03', description: 'Unbekannter Vertrag' },
  ]);
});
afterEach(cleanup);

it('retains the exact statement filter and links its claim back to the original calculation', async () => {
  api.list.mockResolvedValue([
    { id: 'r1', statement_id: 'stmt-a', contract_id: 'k1', amount_due: -25, status: 'open', due_date: '2026-09-01', description: 'Abrechnungsguthaben' },
    { id: 'r2', statement_id: 'stmt-b', contract_id: 'k1', amount_due: 90, status: 'open', due_date: '2026-09-02', description: 'Andere Abrechnung' },
  ]);
  show('/receivables?statement_id=stmt-a');
  expect(await screen.findByText('Abrechnungsguthaben')).toBeInTheDocument();
  expect(screen.queryByText('Andere Abrechnung')).not.toBeInTheDocument();
  expect(api.list).toHaveBeenCalledWith('/receivables?statement_id=stmt-a', expect.objectContaining({ signal: expect.any(AbortSignal) }));
  expect(screen.getByRole('link', { name: 'Einzelabrechnung öffnen' })).toHaveAttribute('href', '/statements?statement_id=stmt-a');
});

it('connects a dunned receivable directly to the proper contract file without issuing writes', async () => {
  show('/receivables?status=dunning');
  const contract = await screen.findByRole('link', { name: 'MV-A' });
  expect(contract).toHaveAttribute('href', '/contracts?contract_id=k1');
  const dunning = screen.getByRole('link', { name: 'Mahnakte öffnen' });
  expect(dunning).toHaveAttribute('href', '/dunning/contracts/k1');
  expect(screen.queryByRole('link', { name: 'MV-B' })).not.toBeInTheDocument();
  // A dunning-level entry with an unavailable contract remains visible, but cannot fabricate a record link.
  const unavailable = screen.getByText('Unbekannter Vertrag').closest('tr');
  expect(within(unavailable).queryByRole('link')).not.toBeInTheDocument();
  fireEvent.click(dunning);
  expect(screen.getByTestId('receivables-route')).toHaveTextContent('/dunning/contracts/k1');
  expect(api.post).not.toHaveBeenCalled();
  expect(api.put).not.toHaveBeenCalled();
  expect(api.del).not.toHaveBeenCalled();
});

it('does not manufacture a dunning or contract link for unrelated or unknown contract rows', async () => {
  show();
  await screen.findByRole('link', { name: 'MV-A' });
  expect(screen.getAllByRole('link', { name: 'Mahnakte öffnen' })).toHaveLength(1);
  expect(screen.getByRole('link', { name: 'MV-B' }))
    .toHaveAttribute('href', '/contracts?contract_id=k2');
  const rowB = screen.getByText('Rückstand B').closest('tr');
  expect(within(rowB).queryByRole('link', { name: 'Mahnakte öffnen' })).not.toBeInTheDocument();
  const unknown = screen.getByText('Unbekannter Vertrag').closest('tr');
  expect(within(unknown).queryByRole('link')).not.toBeInTheDocument();
  expect(screen.getByRole('textbox', { name: /durchsuchen/ })).toBeInTheDocument();
});

it.each([
  ['en-US', 'Open dunning file'],
  ['es-ES', 'Abrir expediente de reclamación'],
])('localizes the dunning destination in %s', async (locale, label) => {
  fixture.locale = locale;
  show('/receivables?contract_id=k1');
  expect(await screen.findByRole('link', { name: label })).toHaveAttribute('href', '/dunning/contracts/k1');
});
