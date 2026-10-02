import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Contracts from '../pages/Contracts';
import ContractEditor from '../components/ContractEditor';
import { bindEditRevision, conditionalHeaders } from '../editRevision';
import de from '../../../i18n/de-DE.json';
import en from '../../../i18n/en-US.json';
import es from '../../../i18n/es-ES.json';

const mocks = vi.hoisted(() => ({ get: vi.fn(), getAll: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(),
  confirm: vi.fn(), invalidateRelated: vi.fn(), role: 'eigentuemer', userId: 'owner-A', portfolios: ['portfolio-A'],
  locale: 'de-DE', translations: null, lifecycleProps: null }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: {
  id: mocks.userId, role: mocks.role, portfolio_access: 'selected', portfolio_ids: mocks.portfolios,
} }) }));
vi.mock('../contexts/DataStoreContext', () => ({
  useDataStore: () => ({ invalidateRelated: mocks.invalidateRelated }),
  // Legacy baseline has only the first 100 reference rows.
  useEntities: () => ({ items: [] }),
}));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => mocks.confirm }));
vi.mock('../components/ContractLifecycle', () => ({ default: props => {
  mocks.lifecycleProps = props;
  return <div role="dialog" aria-label="Synthetic lifecycle"><span>{props.contract.id}</span>
    <button type="button" onClick={props.onClose}>Close lifecycle</button></div>;
} }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: mocks.locale, t: (key, params) => {
  let value = key.split('.').reduce((node, part) => node?.[part], mocks.translations) || key;
  Object.entries(params || {}).forEach(([name, replacement]) => { value = value.replaceAll(`{{${name}}}`, String(replacement)); });
  return value;
} }) }));

const item = (number, overrides = {}) => ({
  id: `contract-${number}`, contract_number: `MV-${String(number).padStart(3, '0')}`,
  property_id: `property-${number}`, unit_id: `unit-${number}`, tenant_id: `tenant-${number}`,
  property_name: `Property ${number}`, unit_label: `Unit ${number}`, tenant_name: `Tenant ${number}`,
  unit_cold_rent: 600, deposit_amount: 0, start_date: '2026-01-01', end_date: '2026-12-31',
  status: 'active', index_rent: 'fixed', service_charge_settlement: 'annual', notice_period: '3 months',
  updated_at: '2026-10-01T08:00:00.123456',
  edit_etag: `"immo-v1:contracts:contract-${number}:2026-10-01T08:00:00.123456Z"`, ...overrides,
});
const envelope = (items, next = null) => ({ items, has_more: next !== null, next_cursor: next, reference_date: '2026-10-01' });
const params = path => new URL(path, 'http://localhost').searchParams;
const workspaceCalls = () => mocks.get.mock.calls.filter(([path]) => path.startsWith('/contracts/workspace/page?'));
const lastQuery = () => params(workspaceCalls().at(-1)[0]);
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const loaded = (number = 1) => screen.findByText(`MV-${String(number).padStart(3, '0')}`, { selector: 'td' });
const apply = () => fireEvent.submit(screen.getByRole('button', { name: de.contractWorkspace.apply }).closest('form'));
const form = () => screen.getByRole('dialog').querySelector('form');
const saveReady = () => waitFor(() => expect(within(screen.getByRole('dialog')).getByRole('button', { name: de.ui.buttons.save, exact: true })).toBeEnabled());
const choices = path => {
  const query = params(path), selected = query.get('selected_id'), offset = Number(query.get('offset'));
  return { items: [{ id: 'choice-1', label: 'First visible choice' }],
    selected: selected ? { id: selected, label: `Selected ${selected}` } : null,
    has_more: offset === 0, offset, limit: 25 };
};
let standard;
beforeEach(() => {
  vi.clearAllMocks(); mocks.role = 'eigentuemer'; mocks.userId = 'owner-A'; mocks.portfolios = ['portfolio-A'];
  mocks.locale = 'de-DE'; mocks.translations = de; mocks.lifecycleProps = null;
  mocks.confirm.mockResolvedValue(true); mocks.post.mockResolvedValue({}); mocks.put.mockResolvedValue({}); mocks.del.mockResolvedValue({});
  standard = async path => {
    if (path.startsWith('/contract-wizard/choices/')) return choices(path);
    if (path.startsWith('/contracts/workspace/page?')) return envelope([item(1)], 'opaque-page-2');
    if (path === '/contracts') return Array.from({ length: 100 }, (_, index) => item(index + 1));
    throw new Error(`Unexpected GET ${path}`);
  };
  mocks.get.mockImplementation(standard);
});

describe('server contract workspace', () => {
  it('finds a Unicode-named contract beyond the legacy first 100 and renders the server-owned joins', async () => {
    mocks.get.mockImplementation(path => path.startsWith('/contracts/workspace/page?')
      ? Promise.resolve(params(path).get('search') === 'Straße Ä_％'
        ? envelope([item(137, { property_name: 'Straße Ä_％', tenant_name: 'Tenant beyond first 100' })])
        : envelope([item(1)])) : standard(path));
    render(<Contracts />);
    await loaded();
    // Also usable against the old first-100 view for the red baseline:
    // its local search cannot retrieve the server-only contract 137.
    const search = screen.queryByLabelText(de.contractWorkspace.search)
      || screen.getByRole('textbox', { name: `${de.ui.form.search} ${de.tenantsContracts.contracts.title}` });
    fireEvent.change(search, { target: { value: 'Straße Ä_％' } });
    if (screen.queryByRole('button', { name: de.contractWorkspace.apply })) apply();
    expect(await loaded(137)).toBeInTheDocument();
    expect(screen.getByText('Tenant beyond first 100', { selector: 'td' })).toBeInTheDocument();
    expect(lastQuery().get('search')).toBe('Straße Ä_％');
    expect(mocks.get.mock.calls.every(([path]) => path.startsWith('/contracts/workspace/page?'))).toBe(true);
    expect(mocks.getAll).not.toHaveBeenCalled();
  });

  it('requests only explicit cursor pages, reaches record 125, and returns with the original query', async () => {
    const rows = Array.from({ length: 125 }, (_, index) => item(index + 1));
    mocks.get.mockImplementation(path => {
      if (!path.startsWith('/contracts/workspace/page?')) return standard(path);
      const page = Number(params(path).get('cursor')?.replace('cursor-', '') || 0);
      return Promise.resolve(envelope(rows.slice(page * 25, page * 25 + 25), page < 4 ? `cursor-${page + 1}` : null));
    });
    render(<Contracts />);
    await loaded();
    expect(workspaceCalls()).toHaveLength(1);
    for (let page = 1; page <= 4; page++) {
      fireEvent.click(screen.getByRole('button', { name: de.contractWorkspace.next, exact: true }));
      await loaded(page * 25 + 1);
    }
    expect(await loaded(125)).toBeInTheDocument();
    expect(workspaceCalls()).toHaveLength(5);
    expect(screen.getByRole('button', { name: de.contractWorkspace.next, exact: true })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: de.contractWorkspace.previous, exact: true }));
    await loaded(76);
    expect(lastQuery().get('cursor')).toBe('cursor-3');
    fireEvent.click(screen.getByRole('button', { name: de.contractWorkspace.firstPage }));
    await loaded();
    expect(lastQuery().has('cursor')).toBe(false);
    expect(screen.queryByText('MV-125', { selector: 'td' })).not.toBeInTheDocument();
  });

  it('applies dates and status before paging, sends sorting to the server and resets its cursor', async () => {
    render(<Contracts />); await loaded();
    fireEvent.change(screen.getByLabelText(de.contractWorkspace.dateFrom), { target: { value: '2026-03-01' } });
    fireEvent.change(screen.getByLabelText(de.contractWorkspace.dateTo), { target: { value: '2027-03-01' } });
    fireEvent.change(screen.getByLabelText(de.tenantsContracts.contracts.status), { target: { value: 'expired' } });
    expect(workspaceCalls()).toHaveLength(1);
    apply(); await waitFor(() => expect(lastQuery().get('status')).toBe('expired'));
    expect(lastQuery().get('date_from')).toBe('2026-03-01'); expect(lastQuery().get('date_to')).toBe('2027-03-01');
    fireEvent.click(await screen.findByRole('button', { name: de.contractWorkspace.next, exact: true }));
    await waitFor(() => expect(lastQuery().get('cursor')).toBe('opaque-page-2'));
    const sortButton = await screen.findByRole('button', { name: 'Nach Mieter sortieren' });
    fireEvent.click(sortButton);
    await waitFor(() => expect(lastQuery().get('sort_by')).toBe('tenant_name'));
    expect(lastQuery().get('sort_order')).toBe('asc'); expect(lastQuery().has('cursor')).toBe(false);
    fireEvent.click(await screen.findByRole('button', { name: 'Nach Mieter sortieren' }));
    await waitFor(() => expect(lastQuery().get('sort_order')).toBe('desc'));
    expect(screen.getByRole('button', { name: 'Nach Mieter sortieren' }).closest('th')).toHaveAttribute('aria-sort', 'descending');
    fireEvent.change(screen.getByLabelText(de.contractWorkspace.pageSize), { target: { value: '100' } });
    await waitFor(() => expect(lastQuery().get('page_size')).toBe('100'));
    expect(lastQuery().get('date_to')).toBe('2027-03-01');
  });

  it.each([[de.contractWorkspace.endingSoon, 'ending_soon'], [de.contractWorkspace.noDeposit, 'no_deposit']])(
    'queries the global %s view rather than filtering only loaded rows', async (name, view) => {
      mocks.get.mockImplementation(path => path.startsWith('/contracts/workspace/page?')
        ? Promise.resolve(envelope([item(params(path).get('view') === view ? 151 : 1)])) : standard(path));
      render(<Contracts />); await loaded(); fireEvent.click(screen.getByRole('button', { name, exact: true }));
      await loaded(151); expect(lastQuery().get('view')).toBe(view);
      expect(screen.getByRole('button', { name, exact: true })).toHaveAttribute('aria-pressed', 'true');
    });

  it('uses the cursor snapshot reference day, distinguishes zero from null and labels summaries as page-only', async () => {
    mocks.get.mockResolvedValue(envelope([item(1, { end_date: '2026-10-02', unit_cold_rent: 0, deposit_amount: null }),
      item(2, { end_date: null, unit_cold_rent: null })]));
    render(<Contracts />); await loaded();
    const cells = within(screen.getByText('MV-001', { selector: 'td' }).closest('tr')).getAllByRole('cell');
    expect(cells[4]).toHaveTextContent('0,00'); expect(cells[10]).toHaveTextContent('—');
    expect(cells[7]).toHaveTextContent('1 Tag');
    expect(screen.getByText('Auf dieser Seite: 2 Verträge · 2 aktiv · 1 enden in 90 Tagen')).toBeInTheDocument();
    expect(screen.getByText(de.contractWorkspace.unitRentHint)).toBeInTheDocument();
  });

  it('keeps failed reads actionable instead of replacing a failure with an empty result', async () => {
    mocks.get.mockRejectedValueOnce(Object.assign(new Error('Server unavailable'), { statusCode: 500 }));
    render(<Contracts />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Server unavailable');
    expect(screen.queryByText(de.contractWorkspace.empty)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: de.contractWorkspace.retry }));
    await loaded(); expect(workspaceCalls()).toHaveLength(2);
  });

  it('submits search with Enter and restores keyboard focus to the same sort and page-size controls after a read', async () => {
    const user = userEvent.setup(); render(<Contracts />); await loaded();
    await user.type(screen.getByLabelText(de.contractWorkspace.search), 'Ä / Straße{Enter}');
    await waitFor(() => expect(lastQuery().get('search')).toBe('Ä / Straße'));
    const sort = await screen.findByRole('button', { name: 'Nach Immobilie sortieren' });
    sort.focus(); await user.keyboard('{Enter}');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Nach Immobilie sortieren' })).toHaveFocus());
    expect(lastQuery().get('sort_by')).toBe('property_name');
    fireEvent.change(screen.getByLabelText(de.contractWorkspace.pageSize), { target: { value: '100' } });
    await waitFor(() => expect(screen.getByLabelText(de.contractWorkspace.pageSize)).toHaveFocus());
    expect(lastQuery().get('page_size')).toBe('100');
  });

  it('requests scoped bounded references only when explicitly expanded and applies the exact property/unit/tenant filter', async () => {
    render(<Contracts />); await loaded();
    expect(mocks.get.mock.calls.some(([path]) => path.includes('/choices/'))).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: de.contractWorkspace.references }));
    await waitFor(() => expect(screen.getByLabelText('Immobilie')).toBeEnabled());
    fireEvent.change(screen.getByLabelText('Immobilie'), { target: { value: 'choice-1' } });
    await waitFor(() => expect(screen.getByLabelText('Einheit')).toBeEnabled());
    const unitQuery = mocks.get.mock.calls.filter(([path]) => path.includes('/choices/units?')).at(-1)[0];
    expect(params(unitQuery).get('property_id')).toBe('choice-1'); expect(params(unitQuery).get('limit')).toBe('25');
    fireEvent.change(screen.getByLabelText('Einheit'), { target: { value: 'choice-1' } });
    fireEvent.change(screen.getByLabelText('Mieter'), { target: { value: 'choice-1' } });
    expect(fireEvent.keyDown(screen.getByLabelText('Mieter suchen'), { key: 'Enter' })).toBe(false);
    expect(workspaceCalls()).toHaveLength(1);
    apply(); await waitFor(() => expect(lastQuery().get('unit_id')).toBe('choice-1'));
    expect(lastQuery().get('property_id')).toBe('choice-1'); expect(lastQuery().get('tenant_id')).toBe('choice-1');
    expect(mocks.getAll).not.toHaveBeenCalled();
  });

  it('closes private dialogs on a fresh server denial instead of retaining the previous scoped subject', async () => {
    render(<Contracts />); await loaded();
    fireEvent.click(screen.getByRole('button', { name: 'Bearbeiten MV-001' })); await saveReady();
    mocks.get.mockRejectedValueOnce(Object.assign(new Error('Access changed'), { statusCode: 403 }));
    // The applied page reload also represents a recheck initiated by a child.
    apply(); await screen.findByRole('alert');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.queryByText('Tenant 1', { selector: 'td' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: de.ui.buttons.new, exact: true })).toBeDisabled();
  });

  it('exports exactly the loaded page with escaped text and cleanup, without implying a full inventory export', async () => {
    mocks.get.mockResolvedValue(envelope([item(137, { tenant_name: '=FORMULA();"quoted"\rline' })], 'next-page'));
    render(<Contracts />); await loaded(137);
    let csv = '', filename = '';
    const originalURL = URL, originalBlob = Blob;
    const create = vi.fn(() => 'blob:owned-contract-page'), revoke = vi.fn();
    vi.stubGlobal('URL', class extends originalURL { static createObjectURL = create; static revokeObjectURL = revoke; });
    vi.stubGlobal('Blob', class extends originalBlob { constructor(parts, options) { super(parts, options); csv = parts.join(''); } });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function () { filename = this.download; });
    vi.useFakeTimers();
    try {
      fireEvent.click(screen.getByRole('button', { name: de.contractWorkspace.exportPage }));
      expect(csv).toContain('MV-137'); expect(csv).not.toContain('MV-001');
      expect(csv).toContain('"\'=FORMULA();""quoted""\rline"');
      expect(filename).toBe('contracts-page-2026-10-01.csv');
      expect(workspaceCalls()).toHaveLength(1); expect(create).toHaveBeenCalledOnce(); expect(revoke).not.toHaveBeenCalled();
      vi.runOnlyPendingTimers(); expect(revoke).toHaveBeenCalledWith('blob:owned-contract-page');
    } finally { vi.useRealTimers(); click.mockRestore(); vi.unstubAllGlobals(); }
  });

  it('accepts the exact server ETag encoding for non-ASCII and reserved IDs without reconstructing its timestamp', async () => {
    const id = "contract:Ä/%'(!)";
    const encoded = encodeURIComponent(id).replace(/[!'()*]/g, char => `%${char.charCodeAt(0).toString(16).toUpperCase()}`);
    const etag = `"immo-v1:contracts:${encoded}:2026-10-01T08:00:00.123456Z"`;
    mocks.get.mockResolvedValue(envelope([item(1, { id, edit_etag: etag })]));
    render(<Contracts />); await loaded();
    fireEvent.click(screen.getByRole('button', { name: 'Löschen MV-001' }));
    await waitFor(() => expect(mocks.del).toHaveBeenCalledOnce());
    const [path, options] = mocks.del.mock.calls[0];
    expect(conditionalHeaders(path, null, options)['If-Match']).toBe(etag);
  });

  it('requires an explicit cursor restart and retains all applied filters', async () => {
    mocks.get.mockImplementation(path => params(path).has('cursor')
      ? Promise.reject(Object.assign(new Error('Cursor expired'), { code: 'cursor_expired' })) : standard(path));
    render(<Contracts />); await loaded();
    fireEvent.change(screen.getByLabelText(de.contractWorkspace.search), { target: { value: 'Literal%_ß' } }); apply();
    await waitFor(() => expect(lastQuery().get('search')).toBe('Literal%_ß'));
    fireEvent.click(await screen.findByRole('button', { name: de.contractWorkspace.next, exact: true }));
    await screen.findByRole('alert');
    const requests = workspaceCalls().length;
    await act(async () => {}); expect(workspaceCalls()).toHaveLength(requests);
    fireEvent.click(screen.getByRole('button', { name: de.contractWorkspace.restart }));
    await loaded(); expect(lastQuery().get('search')).toBe('Literal%_ß'); expect(lastQuery().has('cursor')).toBe(false);
  });

  it('recovers explicitly when a legitimate server page budget is lower than the default without limiting the inventory', async () => {
    mocks.get.mockImplementation(path => path.startsWith('/contracts/workspace/page?') && Number(params(path).get('page_size')) > 10
      ? Promise.reject(Object.assign(new Error('Use a smaller page'), { code: 'page_size_exceeded' })) : standard(path));
    render(<Contracts />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Use a smaller page');
    expect(workspaceCalls()).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: de.contractWorkspace.smallPage }));
    await loaded(); expect(lastQuery().get('page_size')).toBe('1');
    expect(screen.getByRole('button', { name: de.contractWorkspace.next, exact: true })).toBeEnabled();
    fireEvent.change(screen.getByLabelText(de.contractWorkspace.pageSize), { target: { value: '10' } });
    await waitFor(() => expect(lastQuery().get('page_size')).toBe('10'));
    await loaded(); expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it.each([
    envelope([item(1), item(1)]),
    envelope([item(1, { edit_etag: '"immo-v1:contracts:foreign-contract:2026-10-01T08:00:00.123456Z"' })]),
    envelope([item(1, { tenant_name: { private: 'wrong shape' } })]),
    { ...envelope([item(1)]), has_more: true, next_cursor: null },
  ])('rejects malformed pages before rendering their subjects or exposing actions', async response => {
    mocks.get.mockResolvedValue(response); render(<Contracts />);
    expect(await screen.findByRole('alert')).toHaveTextContent(de.contractWorkspace.invalidResult);
    expect(screen.queryByText('MV-001', { selector: 'td' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Bearbeiten MV-001' })).not.toBeInTheDocument();
  });

  it('aborts obsolete search requests and ignores late data even when the transport ignores Abort', async () => {
    const old = deferred();
    mocks.get.mockImplementation(path => path.startsWith('/contracts/workspace/page?') && !params(path).get('search')
      ? old.promise : standard(path));
    render(<Contracts />);
    await waitFor(() => expect(workspaceCalls()).toHaveLength(1));
    const signal = workspaceCalls()[0][1].signal;
    fireEvent.change(screen.getByLabelText(de.contractWorkspace.search), { target: { value: 'fresh' } }); apply();
    await loaded(); expect(signal.aborted).toBe(true);
    await act(async () => old.resolve(envelope([item(333, { tenant_name: 'Stale private tenant' })])));
    expect(screen.queryByText('Stale private tenant')).not.toBeInTheDocument();
  });

  it('remounts on a portfolio/actor switch and does not carry old rows, forms or responses into the new principal', async () => {
    const old = deferred(); mocks.get.mockImplementation(() => old.promise);
    const { rerender } = render(<Contracts />);
    await waitFor(() => expect(workspaceCalls()).toHaveLength(1));
    const signal = workspaceCalls()[0][1].signal;
    mocks.portfolios = ['portfolio-B']; mocks.userId = 'owner-B';
    mocks.get.mockImplementation(path => path.startsWith('/contracts/workspace/page?')
      ? Promise.resolve(envelope([item(222, { tenant_name: 'Authorized B tenant' })])) : standard(path));
    rerender(<Contracts />); await loaded(222);
    expect(signal.aborted).toBe(true);
    await act(async () => old.resolve(envelope([item(333, { tenant_name: 'Foreign A tenant' })])));
    expect(screen.queryByText('Foreign A tenant')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Bearbeiten MV-222' })); await saveReady();
    mocks.role = 'readonly'; rerender(<Contracts />);
    await loaded(222);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: de.ui.buttons.new, exact: true })).not.toBeInTheDocument();
  });

  it('keeps readonly search/paging and lifecycle reads while offering no ordinary mutation controls', async () => {
    mocks.role = 'readonly'; render(<Contracts />); await loaded();
    expect(screen.queryByRole('button', { name: de.ui.buttons.new, exact: true })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Bearbeiten MV-001' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Löschen MV-001' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: de.contractLifecycle.open }));
    expect(mocks.lifecycleProps.contract.id).toBe('contract-1');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled(); expect(mocks.del).not.toHaveBeenCalled();
  });

  it('does not resurrect a delete confirmation after grant revocation and reauthorization', async () => {
    const decision = deferred(); mocks.confirm.mockReturnValue(decision.promise);
    const { rerender } = render(<Contracts />); await loaded();
    fireEvent.click(screen.getByRole('button', { name: 'Löschen MV-001' }));
    expect(mocks.confirm).toHaveBeenCalledOnce();
    mocks.role = 'readonly'; rerender(<Contracts />); await loaded();
    mocks.role = 'eigentuemer'; rerender(<Contracts />); await loaded();
    await act(async () => decision.resolve(true));
    expect(mocks.del).not.toHaveBeenCalled();
  });

  it('deletes explicitly with the exact returned microsecond ETag and suppresses duplicate confirmation clicks', async () => {
    const decision = deferred(); mocks.confirm.mockReturnValue(decision.promise);
    render(<Contracts />); await loaded();
    const remove = screen.getByRole('button', { name: 'Löschen MV-001' });
    fireEvent.click(remove); fireEvent.click(remove); expect(mocks.confirm).toHaveBeenCalledOnce();
    await act(async () => decision.resolve(true));
    await waitFor(() => expect(mocks.del).toHaveBeenCalledOnce());
    const [path, options] = mocks.del.mock.calls[0];
    expect(conditionalHeaders(path, null, options)['If-Match']).toBe(item(1).edit_etag);
  });

  it.each([['de-DE', de], ['en-US', en], ['es-ES', es]])('renders resolved table and editor labels in %s', async (locale, dictionary) => {
    mocks.locale = locale; mocks.translations = dictionary;
    render(<Contracts />); await loaded();
    expect(screen.getByRole('columnheader', { name: dictionary.contractWorkspace.unitColdRent })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: dictionary.contractWorkspace.remaining })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: dictionary.contractWorkspace.sort.replace('{{column}}', dictionary.tenantsContracts.contracts.number) })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: dictionary.contractWorkspace.edit + ' MV-001' })); await saveReadyLocalized(dictionary);
    expect(within(screen.getByRole('dialog')).getByLabelText(dictionary.tenantsContracts.contracts.number, { exact: false })).toHaveValue('MV-001');
    expect(document.body.textContent).not.toMatch(/tenantsContracts\.contracts\.form\.|contractWorkspace\./);
  });
});

const saveReadyLocalized = dictionary => waitFor(() => expect(within(screen.getByRole('dialog')).getByRole('button', { name: dictionary.ui.buttons.save, exact: true })).toBeEnabled());

describe('bounded scoped contract references and edits', () => {
  it('hydrates selected references beyond 100, preserves its original ETag and edited fields when choices refresh', async () => {
    const original = item(137), revision = { collection: 'contracts', id: original.id, updatedAt: original.updated_at,
      etag: original.edit_etag, source: Object.freeze({ ...original }) };
    const save = vi.fn().mockResolvedValue({});
    const { rerender } = render(<ContractEditor initial={bindEditRevision({ ...original }, revision)} onSave={save} onClose={vi.fn()} />);
    await saveReady();
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByLabelText('Immobilie *')).toHaveValue('property-137');
    expect(within(dialog).getByLabelText('Einheit *')).toHaveValue('unit-137');
    expect(within(dialog).getByLabelText('Mieter *')).toHaveValue('tenant-137');
    expect(mocks.get.mock.calls.find(([path]) => path.includes('/choices/units?'))[0]).toContain('property_id=property-137');
    fireEvent.change(within(dialog).getByLabelText('Vertragsnummer *'), { target: { value: 'Edited retained number' } });
    fireEvent.change(within(dialog).getByLabelText('Immobilie suchen'), { target: { value: 'Straße' } });
    await waitFor(() => expect(mocks.get.mock.calls.some(([path]) => params(path).get('search') === 'Straße')).toBe(true));
    await saveReady();
    rerender(<ContractEditor initial={bindEditRevision({ ...original, updated_at: '2026-10-02T01:00:00.222222' },
      { ...revision, updatedAt: '2026-10-02T01:00:00.222222', etag: '"immo-v1:contracts:contract-137:2026-10-02T01:00:00.222222Z"' })} onSave={save} onClose={vi.fn()} />);
    expect(within(dialog).getByLabelText('Vertragsnummer *')).toHaveValue('Edited retained number');
    fireEvent.submit(form()); await waitFor(() => expect(save).toHaveBeenCalledOnce());
    expect(save.mock.calls[0][0].contract_number).toBe('Edited retained number');
    expect(conditionalHeaders('/contracts/contract-137', save.mock.calls[0][0])['If-Match']).toBe(original.edit_etag);
    expect(mocks.getAll).not.toHaveBeenCalled();
  });

  it('pages reference choices explicitly, keeps searches from implicitly saving and clears a unit when its property changes', async () => {
    const save = vi.fn(); render(<ContractEditor initial={item(1)} onSave={save} onClose={vi.fn()} />); await saveReady();
    const dialog = screen.getByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Weitere Immobilie laden' }));
    await waitFor(() => expect(mocks.get.mock.calls.some(([path]) => path.includes('/choices/properties?') && params(path).get('offset') === '25')).toBe(true));
    await saveReady();
    const search = within(dialog).getByLabelText('Immobilie suchen');
    expect(fireEvent.keyDown(search, { key: 'Enter', code: 'Enter' })).toBe(false);
    expect(save).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText('Immobilie *'), { target: { value: 'choice-1' } });
    await waitFor(() => expect(within(dialog).getByLabelText('Einheit *')).toHaveValue(''));
    await waitFor(() => expect(mocks.get.mock.calls.some(([path]) => path.includes('/choices/units?') && params(path).get('property_id') === 'choice-1')).toBe(true));
    expect(save).not.toHaveBeenCalled();
  });

  it('keeps an archived selected tenant through its exact protected lookup rather than permitting new archived choices', async () => {
    mocks.get.mockImplementation(path => path.startsWith('/choices/') ? standard(path) : path.startsWith('/contract-wizard/choices/tenants?')
      ? Promise.resolve({ ...choices(path), selected: null }) : path === '/tenants/tenant-137'
        ? Promise.resolve({ id: 'tenant-137', full_name: 'Historical selected tenant', archived: true }) : standard(path));
    render(<ContractEditor initial={item(137)} onSave={vi.fn()} onClose={vi.fn()} />); await saveReady();
    expect(screen.getByRole('option', { name: 'Historical selected tenant · archiviert' })).toBeInTheDocument();
    expect(mocks.get.mock.calls.some(([path]) => path === '/tenants/tenant-137')).toBe(true);
  });

  it('accepts an active selected tenant already in the returned page without incorrectly treating it as archived', async () => {
    mocks.get.mockImplementation(path => path.startsWith('/contract-wizard/choices/tenants?')
      ? Promise.resolve({ ...choices(path), selected: null, items: [{ id: 'tenant-137', label: 'Active selected tenant' }] })
      : standard(path));
    render(<ContractEditor initial={item(137)} onSave={vi.fn()} onClose={vi.fn()} />); await saveReady();
    expect(screen.getByRole('option', { name: 'Active selected tenant' })).toBeInTheDocument();
    expect(mocks.get.mock.calls.some(([path]) => path === '/tenants/tenant-137')).toBe(false);
  });

  it('blocks a write on unavailable scoped references, surfaces the server error and leaves entered values intact', async () => {
    const save = vi.fn();
    mocks.get.mockImplementation(path => path.includes('/choices/units?') ? Promise.reject(new Error('Unit not in current scope')) : standard(path));
    render(<ContractEditor initial={item(137)} onSave={save} onClose={vi.fn()} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Unit not in current scope');
    const number = within(screen.getByRole('dialog')).getByLabelText('Vertragsnummer *');
    fireEvent.change(number, { target: { value: 'Retain this correction' } });
    expect(screen.getByRole('button', { name: de.ui.buttons.save, exact: true })).toBeDisabled();
    fireEvent.submit(form()); expect(save).not.toHaveBeenCalled();
    mocks.get.mockImplementation(standard);
    fireEvent.click(screen.getByRole('button', { name: de.ui.buttons.retry }));
    await saveReady(); expect(number).toHaveValue('Retain this correction');
  });

  it('saves through the ordinary conditional CRUD route and retains an actionable 409 without upgrading the revision', async () => {
    mocks.put.mockRejectedValue(Object.assign(new Error('Confirmed lifecycle fields cannot be changed'), { statusCode: 409 }));
    render(<Contracts />); await loaded();
    fireEvent.click(screen.getByRole('button', { name: 'Bearbeiten MV-001' })); await saveReady();
    fireEvent.change(within(screen.getByRole('dialog')).getByLabelText('Kündigungsfrist'), { target: { value: 'Reviewed local correction' } });
    fireEvent.submit(form());
    expect(await within(screen.getByRole('dialog')).findByRole('alert')).toHaveTextContent('Confirmed lifecycle fields cannot be changed');
    expect(mocks.put).toHaveBeenCalledOnce();
    const [path, payload, options] = mocks.put.mock.calls[0];
    expect(conditionalHeaders(path, payload, options)['If-Match']).toBe(item(1).edit_etag);
    expect(within(screen.getByRole('dialog')).getByLabelText('Kündigungsfrist')).toHaveValue('Reviewed local correction');
    expect(mocks.invalidateRelated).not.toHaveBeenCalled();
  });

  it('uses the newly reviewed ETag only after an explicit conflict reconciliation and keeps the chosen local correction', async () => {
    const updated = item(1, { updated_at: '2026-10-02T01:00:00.654321', notice_period: 'Concurrent correction',
      edit_etag: '"immo-v1:contracts:contract-1:2026-10-02T01:00:00.654321Z"' });
    mocks.put.mockRejectedValueOnce(Object.assign(new Error('Contract changed'), {
      statusCode: 412, isEditConflict: true, resourcePath: '/contracts/contract-1',
    })).mockResolvedValueOnce({});
    mocks.get.mockImplementation(path => path === '/contracts/contract-1'
      ? Promise.resolve(bindEditRevision({ ...updated }, { collection: 'contracts', id: updated.id,
        updatedAt: updated.updated_at, etag: updated.edit_etag, source: Object.freeze({ ...updated }) })) : standard(path));
    render(<Contracts />); await loaded();
    fireEvent.click(screen.getByRole('button', { name: 'Bearbeiten MV-001' })); await saveReady();
    const dialog = screen.getByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Kündigungsfrist'), { target: { value: 'Chosen local correction' } });
    fireEvent.submit(form());
    await within(dialog).findByRole('alert');
    expect(conditionalHeaders(...mocks.put.mock.calls[0])['If-Match']).toBe(item(1).edit_etag);
    fireEvent.click(within(dialog).getByRole('button', { name: de.editConflict.inspect }));
    const choice = await within(dialog).findByRole('combobox', { name: de.editConflict.choose.replace('{{field}}', 'Kündigungsfrist') });
    fireEvent.change(choice, { target: { value: 'draft' } });
    fireEvent.click(within(dialog).getByRole('button', { name: de.editConflict.reconcile }));
    expect(mocks.put).toHaveBeenCalledOnce();
    expect(within(dialog).getByLabelText('Kündigungsfrist')).toHaveValue('Chosen local correction');
    fireEvent.submit(form()); await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(2));
    expect(conditionalHeaders(...mocks.put.mock.calls[1])['If-Match']).toBe(updated.edit_etag);
    expect(mocks.put.mock.calls[1][1].notice_period).toBe('Chosen local correction');
  });
});
