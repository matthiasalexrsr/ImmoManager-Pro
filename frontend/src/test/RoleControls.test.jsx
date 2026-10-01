import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import Accounts from '../pages/Accounts';
import Meters from '../pages/Meters';
import Maintenance from '../pages/Maintenance';
import Properties from '../pages/Properties';
import Statements from '../pages/Statements';
import Documents from '../pages/Documents';
import RentCharges from '../pages/RentCharges';
import RentOverview from '../pages/RentOverview';
import BankPaymentModal from '../components/BankPaymentModal';
import RentGenerationModal from '../components/RentGenerationModal';
import PhotoDropZone from '../components/PhotoDropZone';
import UpdateSection from '../pages/settings/UpdateSection';
import DiagnosticsPanel from '../components/DiagnosticsPanel';
import AutotestSection from '../pages/settings/AutotestSection';
import { DevModeProvider, useDevMode } from '../contexts/DevModeContext';

const mocks = vi.hoisted(() => ({ role: 'eigentuemer', permissions: undefined,
  get: vi.fn(), getAll: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), postForm: vi.fn(), getBlob: vi.fn(), confirm: vi.fn() }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'actor', role: mocks.role, write_permissions: mocks.permissions }, role: mocks.role }) }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: 'de-DE', t: key => key }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => mocks.confirm }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => ({ invalidateRelated: vi.fn() }), useEntities: () => ({ items: [], loading: false, error: null, reload: vi.fn() }) }));
vi.mock('../components/DataTable', () => ({ default: ({ data, onAdd, onEdit, onDelete, onRowClick, columns }) => <section data-testid="table">
  {onAdd && <button onClick={onAdd}>Create record</button>}
  {data.map(row => <div key={row.id}><span>{row.name || row.label || row.id}</span>
    {onEdit && <button onClick={() => onEdit(row)}>Edit record</button>}
    {onDelete && <button onClick={() => onDelete(row)}>Delete record</button>}
    {onRowClick && <button onClick={() => onRowClick(row)}>View record</button>}
    {columns?.filter(col => col.key === 'actions').map(col => <span key={col.key}>{col.render(undefined, row)}</span>)}
  </div>)}
</section> }));
const account = { id: 'account', portfolio_id: 'portfolio', name: 'Existing bank account', account_type: 'Girokonto', balance: 0 };
const pending = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
beforeEach(() => {
  vi.clearAllMocks(); mocks.role = 'eigentuemer'; mocks.permissions = undefined;
  mocks.getAll.mockResolvedValue([]); mocks.get.mockResolvedValue([]); mocks.confirm.mockResolvedValue(true);
  for (const method of ['post', 'put', 'patch', 'del', 'postForm']) mocks[method].mockResolvedValue({});
});
function mount(Component) { return render(<MemoryRouter>{createElement(Component)}</MemoryRouter>); }
const roles = ['eigentuemer', 'verwalter', 'buchhaltung', 'techniker', 'readonly'];
const cases = [
  [Accounts, 'finance'], [RentCharges, 'finance'], [Statements, 'billing'],
  [Meters, 'operations'], [Maintenance, 'operations'], [Documents, 'documents'],
];
const allowed = (role, capability) => ['eigentuemer', 'verwalter'].includes(role)
  || role === 'buchhaltung' && ['finance', 'billing', 'documents'].includes(capability)
  || role === 'techniker' && ['operations', 'documents'].includes(capability);

describe('role-specific page controls', () => {
  for (const [Component, capability] of cases) it.each(roles)(`${Component.name}: %s can create only in its business area`, async role => {
    mocks.role = role; mount(Component);
    await screen.findByTestId('table');
    expect(screen.queryByRole('button', { name: 'Create record' }) !== null).toBe(allowed(role, capability));
    expect(mocks.post).not.toHaveBeenCalled();
    expect(mocks.put).not.toHaveBeenCalled();
  });
  it.each(roles)('Properties: %s keeps read navigation and receives only allowed portfolio actions', async role => {
    mocks.role = role; mount(Properties);
    await screen.findByText('properties.emptyTitle');
    expect(screen.queryAllByRole('button', { name: 'properties.create' }).length > 0).toBe(['eigentuemer', 'verwalter'].includes(role));
    expect(mocks.post).not.toHaveBeenCalled();
  });
  it('hides finance editing from an owner with an explicit empty server grant', async () => {
    mocks.permissions = []; mount(Accounts); await screen.findByTestId('table');
    expect(screen.queryByRole('button', { name: 'Create record' })).not.toBeInTheDocument();
  });
  it('closes the original draft after a role change and does not resurrect it when permission returns', async () => {
    mocks.getAll.mockImplementation(async path => path === '/accounts' ? [account] : [{ id: 'portfolio', name: 'Portfolio' }]);
    const ui = mount(Accounts); fireEvent.click(await screen.findByRole('button', { name: 'Edit record' }));
    fireEvent.change(screen.getByLabelText(/finance.accounts.form.name/), { target: { value: 'Private unfinished draft' } });
    mocks.role = 'techniker'; ui.rerender(<MemoryRouter><Accounts /></MemoryRouter>);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    mocks.role = 'buchhaltung'; ui.rerender(<MemoryRouter><Accounts /></MemoryRouter>);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(mocks.put).not.toHaveBeenCalled();
  });
  it('never revives a pending deletion after revoke and restore during confirmation', async () => {
    const confirmation = pending(); mocks.confirm.mockReturnValue(confirmation.promise);
    mocks.getAll.mockImplementation(async path => path === '/accounts' ? [account] : []);
    const ui = mount(Accounts); fireEvent.click(await screen.findByRole('button', { name: 'Delete record' }));
    mocks.role = 'readonly'; ui.rerender(<MemoryRouter><Accounts /></MemoryRouter>);
    mocks.role = 'eigentuemer'; ui.rerender(<MemoryRouter><Accounts /></MemoryRouter>);
    await act(async () => confirmation.resolve(true));
    expect(mocks.del).not.toHaveBeenCalled();
    expect(screen.getByText(account.name)).toBeInTheDocument();
  });
  it('allows read-only meter reading navigation without edit or creation controls', async () => {
    mocks.role = 'readonly'; mocks.getAll.mockImplementation(async path => path === '/meters' ? [{ id: 'meter', serial_number: 'Meter M', meter_type: 'cold_water' }] : []);
    mount(Meters); fireEvent.click(await screen.findByRole('button', { name: 'View record' }));
    expect(screen.getByText(/Ablesungen/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Zähler bearbeiten|Ablesung erfassen/ })).not.toBeInTheDocument();
  });
  it('keeps the billing period readable for technicians while hiding generation, revision, cost and workflow commands', async () => {
    mocks.role = 'techniker'; mocks.getAll.mockImplementation(async path => path === '/billing/periods' ? [{ id: 'period', status: 'review', label: 'Historical billing', start_date: '2025-01-01', end_date: '2025-12-31' }] : []);
    mocks.get.mockImplementation(async path => path.endsWith('/preflight') ? { has_blockers: false, blockers: [], warnings: [], metrics: {} } : { id: 'period', owner_cost_share: null });
    mount(Statements); fireEvent.click(await screen.findByRole('button', { name: 'View record' }));
    await screen.findByText('Historical billing');
    for (const label of ['generate', 'finalize', 'startCorrection', 'submitReview', 'revertDraft', 'book']) {
      expect(screen.queryByRole('button', { name: new RegExp(`pages.statements.${label}$`) })).not.toBeInTheDocument();
    }
    expect(screen.getByRole('button', { name: 'pages.statements.csvExport' })).toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled();
  });
});

describe('special command capability boundaries', () => {
  it.each(['techniker', 'readonly'])('blocks standalone financial modals for %s before preview/load/post', role => {
    mocks.role = role;
    const ui = render(<RentGenerationModal contracts={[]} onClose={vi.fn()} onGenerated={vi.fn()} />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument(); ui.unmount();
    render(<BankPaymentModal row={{ id: 'charge', remaining: 100 }} onClose={vi.fn()} onSave={vi.fn()} />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(mocks.getAll).not.toHaveBeenCalled(); expect(mocks.post).not.toHaveBeenCalled();
  });
  it.each(['eigentuemer', 'verwalter', 'buchhaltung'])('provides monthly preview for %s', role => {
    mocks.role = role; render(<RentGenerationModal contracts={[]} onClose={vi.fn()} onGenerated={vi.fn()} />);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });
  it('does not continue monthly generation after permission disappears during the preview request', async () => {
    const response = pending(); mocks.post.mockReturnValue(response.promise); const close = vi.fn();
    const ui = render(<RentGenerationModal contracts={[]} onClose={close} onGenerated={vi.fn()} />);
    fireEvent.submit(screen.getByRole('dialog').querySelector('form'));
    mocks.role = 'readonly'; ui.rerender(<RentGenerationModal contracts={[]} onClose={close} onGenerated={vi.fn()} />);
    await act(async () => response.resolve({ policy: 'full_month', candidates: [], existing: [], skipped_contracts: [], preview_hash: 'hash', total_amount: 0 }));
    expect(close).toHaveBeenCalled(); expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(mocks.post).toHaveBeenCalledTimes(1);
  });
  it.each(['techniker', 'readonly'])('keeps payment history available without payment/reversal actions for %s', async role => {
    mocks.role = role;
    mocks.getAll.mockImplementation(async path => path === '/rent-charges' ? [{ id: 'charge', contract_id: 'contract', month: '2026-01', cold_rent: 100, amount_paid: 0 }] : path === '/contracts' ? [{ id: 'contract', tenant_id: 'tenant' }] : path === '/tenants' ? [{ id: 'tenant', full_name: 'Tenant A' }] : []);
    mount(RentOverview); await screen.findByText('charge');
    expect(screen.queryByRole('button', { name: /recordPayment|allocateBooking/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /history/ })).toBeInTheDocument();
  });
  it.each(['techniker', 'buchhaltung'])('shows document upload controls for %s', async role => {
    mocks.role = role; render(<PhotoDropZone entityType="unit" entityId="one" />);
    expect(screen.getByLabelText('Fotos hochladen')).toBeInTheDocument();
  });
  it('preserves photo viewing without a file upload or delete control for readonly', async () => {
    mocks.role = 'readonly'; render(<PhotoDropZone entityType="unit" entityId="one" />);
    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    expect(screen.queryByLabelText('Fotos hochladen')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Foto löschen')).not.toBeInTheDocument();
  });
  it.each(['buchhaltung', 'techniker', 'readonly'])('does not expose update or diagnostics actions for %s', role => {
    mocks.role = role; const ui = render(<UpdateSection />); expect(ui.container).toBeEmptyDOMElement(); ui.unmount();
    const diagnostics = render(<AutotestSection />); expect(diagnostics.container).toBeEmptyDOMElement(); diagnostics.unmount();
    const consistency = render(<DiagnosticsPanel onClose={vi.fn()} />); expect(consistency.container).toBeEmptyDOMElement();
    expect(mocks.post).not.toHaveBeenCalled();
  });
  it('keeps the complete diagnostics report usable for an authorized administrator', async () => {
    mocks.get.mockResolvedValue({
      total_tests: 1, passed: 1, failed: 0, warnings: 0, total_issues: 0, duration_ms: 5,
      results: [{ test: 'FK integrity', passed: true, checked: 3, duration_ms: 5, issues: [] }],
    });
    render(<DiagnosticsPanel onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Run Tests' }));
    expect(await screen.findByText('FK integrity')).toBeInTheDocument();
    expect(screen.getByText('1 passed')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Download' })).toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledWith('/diagnostics/run');
  });
  it('ignores the developer shortcut for non-admins and closes the active overlay on revocation', async () => {
    function Probe() { const dev = useDevMode(); return <output>{String(dev.enabled)}</output>; }
    mocks.role = 'techniker'; const ui = render(<DevModeProvider><Probe /></DevModeProvider>);
    fireEvent.keyDown(window, { key: 'D', ctrlKey: true, shiftKey: true });
    expect(screen.getByText('false')).toBeInTheDocument(); expect(mocks.get).not.toHaveBeenCalled();
    mocks.role = 'eigentuemer'; ui.rerender(<DevModeProvider><Probe /></DevModeProvider>);
    fireEvent.keyDown(window, { key: 'D', ctrlKey: true, shiftKey: true });
    expect(screen.getByText('true')).toBeInTheDocument();
    mocks.role = 'readonly'; ui.rerender(<DevModeProvider><Probe /></DevModeProvider>);
    expect(screen.getByText('false')).toBeInTheDocument();
  });
});
