import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import Statements from '../pages/Statements';
import { emptySummary, postedSummary } from './fixtures/settlements';
import { ownerPeriod } from './fixtures/ownerShare';

const mocks = vi.hoisted(() => ({ getAll: vi.fn(), get: vi.fn(), post: vi.fn(), put: vi.fn(), role: 'eigentuemer' }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ role: mocks.role }) }));
// Test only the page boundary here; the real workspace has its own actual-hook
// and protected-read suites, followed by coordinated native browser proofs.
vi.mock('../features/billingDisputes/BillingDisputeWorkspace', () => ({ default: ({ periodId, propertyId }) =>
  <section aria-label="Widerspruchsakten" data-period={periodId} data-property={propertyId} /> }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../i18n', () => {
  const t = key => key.split('.').at(-1);
  return { useTranslation: () => ({ t, locale: 'de-DE' }) };
});
vi.mock('../components/StatusBadge', () => ({ default: ({ status }) => <span>{status}</span> }));
vi.mock('../components/DataTable', () => ({
  default: ({ title, data, onEdit, onRowClick, onAdd }) => (
    <section aria-label={title}>
      <h2>{title}</h2>
      {onAdd && <button onClick={onAdd}>Add {title}</button>}
      {data.map(row => (
        <div key={row.id}>
          {onEdit && <button onClick={() => onEdit(row)}>Open {row.id}</button>}
          {onRowClick && <button onClick={() => onRowClick(row)}>View {row.id}</button>}
          <span>{row.description || row.unit_label || row.label}</span>
          {row.total_costs != null && <output data-testid={`total-${row.id}`}>{row.total_costs}</output>}
        </div>
      ))}
    </section>
  ),
}));

const period = { id: 'period', property_id: 'property', label: 'Abrechnung 2025',
  start_date: '2025-01-01', end_date: '2025-12-31', status: 'review' };
const fixture = {
  '/billing/periods': [period],
  '/billing/cost-items': [{ id: 'cost', billing_period_id: 'period', amount: 12.34, description: 'Wasser' }],
  '/billing/statements': [],
  '/properties': [{ id: 'property', name: 'Musterhaus' }],
  '/units': [], '/billing/allocation-keys': [], '/contracts': [], '/tenants': [],
};
const ready = { has_blockers: false, blockers: [], warnings: [], metrics: {} };
let lists;
const read = async path => {
  if (path in lists) return structuredClone(lists[path]);
  if (path.endsWith('/preflight')) return structuredClone(ready);
  if (path.endsWith('/settlements')) return emptySummary(path.split('/').at(-2));
  if (path.startsWith('/billing/periods/')) return { ...period, id: path.split('/').at(-1), owner_cost_share: null };
  throw new Error(`Unexpected GET: ${path}`);
};
const deferred = () => {
  let resolve;
  const promise = new Promise(r => { resolve = r; });
  return { promise, resolve };
};
async function openPeriod(id = 'period') {
  const button = await screen.findByRole('button', { name: `Open ${id}` });
  await act(async () => { fireEvent.click(button); });
}

describe('Statements workflow reliability', () => {
  beforeEach(() => {
    mocks.role = 'eigentuemer';
    lists = structuredClone(fixture);
    mocks.getAll.mockReset().mockImplementation(read);
    mocks.get.mockReset().mockImplementation(read);
    mocks.post.mockReset().mockResolvedValue({});
    mocks.put.mockReset().mockResolvedValue({});
  });

  it('loads every paginated billing and reference list', async () => {
    render(<Statements />);
    await screen.findByRole('button', { name: 'Open period' });
    for (const path of Object.keys(lists)) {
      expect(mocks.getAll).toHaveBeenCalledWith(path, expect.objectContaining({ signal: expect.any(AbortSignal) }));
    }
  });

  it('adds decimal-string amounts correctly in list and detail totals', async () => {
    lists['/billing/cost-items'] = [
      { id: 'a', billing_period_id: 'period', amount: '10.25' },
      { id: 'b', billing_period_id: 'period', amount: '20.10' },
    ];
    const { container } = render(<Statements />);
    expect(await screen.findByTestId('total-period')).toHaveTextContent('30.35');
    await openPeriod();
    expect(container.querySelector('.stats-grid')).toHaveTextContent('30.35 €');
  });

  it('keeps load failures visible and offers a working retry', async () => {
    const fail = async () => { throw new Error('Server nicht erreichbar'); };
    mocks.get.mockImplementation(fail);
    mocks.getAll.mockImplementation(fail);
    render(<Statements />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Server nicht erreichbar');
    expect(screen.queryByRole('button', { name: /Add/ })).not.toBeInTheDocument();
    mocks.get.mockImplementation(read);
    mocks.getAll.mockImplementation(read);
    fireEvent.click(screen.getByRole('button', { name: 'retry' }));
    await screen.findByRole('button', { name: 'Open period' });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows mutation errors in the detail view', async () => {
    mocks.post.mockRejectedValue(new Error('Generierung fehlgeschlagen'));
    render(<Statements />);
    await openPeriod();
    await screen.findByText('readyToGenerate');
    fireEvent.click(screen.getByRole('button', { name: 'generate' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Generierung fehlgeschlagen');
  });

  it('opens a correction dialog and submits the encoded reason', async () => {
    mocks.post.mockResolvedValue({ new_period_id: 'revision' });
    render(<Statements />);
    await openPeriod();
    fireEvent.click(screen.getByRole('button', { name: 'startCorrection' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: 'Wasser & Heizung' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'save' }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith(
      '/billing/periods/period/revisions?revision_notes=Wasser%20%26%20Heizung', {},
    ));
    await waitFor(() => expect(mocks.get).toHaveBeenCalledWith('/billing/periods/revision'));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it.each(['finalized', 'delivered', 'disputed', 'corrected'])('mounts the genuine dispute workspace for %s without the obsolete reason-only POST', async status => {
    lists['/billing/periods'][0].status = status;
    render(<Statements />);
    await openPeriod();
    expect(screen.getByRole('region', { name: 'Widerspruchsakten' })).toHaveAttribute('data-period', 'period');
    expect(screen.getByRole('region', { name: 'Widerspruchsakten' })).toHaveAttribute('data-property', 'property');
    expect(screen.queryByRole('button', { name: 'dispute' })).not.toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it.each(['draft', 'review'])('keeps the immutable journal entry outside %s periods', async status => {
    lists['/billing/periods'][0].status = status; render(<Statements />); await openPeriod();
    expect(screen.queryByRole('region', { name: 'Widerspruchsakten' })).not.toBeInTheDocument();
  });

  it('retains authorized dispute reads for a readonly actor in immutable period details', async () => {
    mocks.role = 'readonly'; lists['/billing/periods'][0].status = 'finalized'; render(<Statements />);
    fireEvent.click(await screen.findByRole('button', { name: 'View period' }));
    expect(screen.getByRole('region', { name: 'Widerspruchsakten' })).toHaveAttribute('data-period', 'period');
    expect(screen.queryByRole('button', { name: 'startCorrection' })).not.toBeInTheDocument();
  });

  it('blocks generation and finalization after a failed preflight until retry succeeds', async () => {
    mocks.get.mockImplementation(path => path.endsWith('/preflight')
      ? Promise.reject(new Error('Prüfung nicht erreichbar')) : read(path));
    render(<Statements />);
    await openPeriod();
    expect(await screen.findByRole('alert')).toHaveTextContent('Prüfung nicht erreichbar');
    expect(screen.getByRole('button', { name: 'generate' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'finalize' })).toBeDisabled();
    mocks.get.mockImplementation(read);
    fireEvent.click(screen.getByRole('button', { name: 'recheck' }));
    await screen.findByText('readyToGenerate');
    expect(screen.getByRole('button', { name: 'generate' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'finalize' })).toBeEnabled();
  });

  it('does not apply a late preflight result to a different period', async () => {
    const first = deferred();
    const second = deferred();
    lists['/billing/periods'].push({ ...period, id: 'second', label: 'Abrechnung 2024' });
    mocks.get.mockImplementation(path => path.endsWith('/preflight')
      ? (path.includes('/second/') ? second.promise : first.promise) : read(path));
    render(<Statements />);
    await openPeriod();
    fireEvent.click(screen.getByRole('button', { name: /back/ }));
    await openPeriod('second');
    await act(async () => { first.resolve(ready); });
    expect(screen.getByRole('button', { name: 'generate' })).toBeDisabled();
    expect(screen.queryByText('readyToGenerate')).not.toBeInTheDocument();
    await act(async () => { second.resolve({ ...ready, has_blockers: true }); });
    await screen.findByText('blocked');
    expect(screen.getByRole('button', { name: 'finalize' })).toBeDisabled();
  });

  it('aborts list requests when the page unmounts', async () => {
    const pending = deferred();
    mocks.getAll.mockReturnValue(pending.promise);
    mocks.get.mockReturnValue(pending.promise);
    const { unmount } = render(<Statements />);
    const calls = mocks.getAll.mock.calls;
    expect(calls).toHaveLength(8);
    const signals = calls.map(([, options]) => options.signal);
    unmount();
    expect(signals.every(signal => signal.aborted)).toBe(true);
    await act(async () => { pending.resolve([]); });
  });

  it('retains a correction reason after a failed submission', async () => {
    mocks.post.mockRejectedValueOnce(new Error('Korrektur abgelehnt'));
    render(<Statements />);
    await openPeriod();
    fireEvent.click(screen.getByRole('button', { name: 'startCorrection' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: 'Wasser korrigieren' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'save' }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Korrektur abgelehnt');
    expect(within(dialog).getByRole('textbox')).toHaveValue('Wasser korrigieren');
    expect(within(dialog).getByRole('button', { name: 'save' })).toBeEnabled();
    fireEvent.click(within(dialog).getByRole('button', { name: 'save' }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    await screen.findByText('readyToGenerate');
  });

  it('rechecks preflight after saving a cost item', async () => {
    lists['/billing/cost-items'][0].allocation_key_id = 'key';
    lists['/billing/allocation-keys'] = [{ id: 'key', name: 'Fläche', key_type: 'area' }];
    let checks = 0;
    mocks.get.mockImplementation(path => path.endsWith('/preflight')
      ? Promise.resolve({ ...ready, has_blockers: ++checks > 1 }) : read(path));
    render(<Statements />);
    await openPeriod();
    await screen.findByText('readyToGenerate');
    fireEvent.click(screen.getByRole('button', { name: 'Open cost' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByRole('spinbutton'), { target: { value: '15.00' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'save' }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalled());
    await screen.findByText('blocked');
    expect(screen.getByRole('button', { name: 'finalize' })).toBeDisabled();
    expect(checks).toBe(2);
  });

  it.each([null, {}, []])('rejects an invalid preflight response: %j', async result => {
    mocks.get.mockImplementation(path => path.endsWith('/preflight') ? Promise.resolve(result) : read(path));
    render(<Statements />);
    await openPeriod();
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'generate' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'finalize' })).toBeDisabled();
  });

  it('does not navigate back when a mutation for the previous period finishes', async () => {
    lists['/billing/periods'][0].status = 'draft';
    lists['/billing/periods'].push({ ...period, id: 'second', label: 'Second period' });
    const pending = deferred();
    mocks.post.mockReturnValue(pending.promise);
    render(<Statements />);
    await openPeriod();
    await screen.findByText('readyToGenerate');
    fireEvent.click(screen.getByRole('button', { name: 'submitReview' }));
    fireEvent.click(screen.getByRole('button', { name: /back/ }));
    await openPeriod('second');
    await act(async () => { pending.resolve({ ...period, status: 'review' }); });
    expect(await screen.findByRole('heading', { name: 'Second period' })).toBeInTheDocument();
    await screen.findByText('readyToGenerate');
    expect(screen.getByRole('heading', { name: 'Second period' })).toBeInTheDocument();
  });

  it('loads persisted credits after posting and after an idempotent replay', async () => {
    lists['/billing/periods'][0].status = 'finalized';
    let summary = emptySummary();
    mocks.get.mockImplementation(path => path.endsWith('/settlements') ? Promise.resolve(summary) : read(path));
    mocks.post.mockImplementation(async () => {
      summary = postedSummary();
      return mocks.post.mock.calls.length === 1 ? summary : { ...summary,
        created_receivables: 0, created_credits: 0, created_settlements: 0, existing_count: 3 };
    });
    render(<Statements />);
    await openPeriod();
    fireEvent.click(screen.getByRole('button', { name: 'book' }));
    await screen.findByText('posted');
    await waitFor(() => expect(mocks.get.mock.calls.filter(([path]) => path.endsWith('/settlements'))).toHaveLength(2));
    expect(mocks.post).toHaveBeenCalledWith('/billing/periods/period/create-receivables', {});
    fireEvent.click(screen.getByRole('button', { name: 'book' }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(mocks.get.mock.calls.filter(([path]) => path.endsWith('/settlements'))).toHaveLength(3));
  });

  it('retries a failed post-booking read without repeating the successful write', async () => {
    lists['/billing/periods'][0].status = 'finalized';
    let reads = 0;
    mocks.get.mockImplementation(path => path.endsWith('/settlements')
      ? (++reads === 2 ? Promise.reject(new Error('Settlement refresh unavailable')) : Promise.resolve(emptySummary())) : read(path));
    mocks.post.mockResolvedValue(postedSummary());
    render(<Statements />);
    await openPeriod();
    fireEvent.click(screen.getByRole('button', { name: 'book' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Settlement refresh unavailable');
    fireEvent.click(screen.getByRole('button', { name: 'retry' }));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    expect(mocks.post).toHaveBeenCalledTimes(1);
    expect(reads).toBe(3);
  });

  it('reconciles an incomplete write response without claiming success', async () => {
    lists['/billing/periods'][0].status = 'finalized';
    mocks.post.mockResolvedValue({ created_receivables: 0 });
    render(<Statements />);
    await openPeriod();
    fireEvent.click(screen.getByRole('button', { name: 'book' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('postingUnknown');
    expect(screen.queryByText('posted')).not.toBeInTheDocument();
    await waitFor(() => expect(mocks.get.mock.calls.filter(([path]) => path.endsWith('/settlements'))).toHaveLength(2));
  });

  it.each(['edit', 'create'])('preserves cost input when preflight completes during %s', async mode => {
    const pending = deferred();
    mocks.get.mockImplementation(path => path.endsWith('/preflight') ? pending.promise : read(path));
    lists['/billing/cost-items'][0].allocation_key_id = 'key';
    lists['/billing/allocation-keys'] = [{ id: 'key', name: 'Fläche', key_type: 'area_sqm' }];
    render(<Statements />);
    await openPeriod();
    fireEvent.click(screen.getByRole('button', { name: mode === 'edit' ? 'Open cost' : 'Add costItems' }));
    const dialog = screen.getByRole('dialog');
    const amount = within(dialog).getByRole('spinbutton');
    fireEvent.change(amount, { target: { value: '700.00' } });
    await act(async () => pending.resolve(ready));
    expect(within(dialog).getByRole('spinbutton')).toHaveValue(700);
    if (mode === 'edit') {
      fireEvent.click(within(dialog).getByRole('button', { name: 'save' }));
      await waitFor(() => expect(mocks.put).toHaveBeenCalledWith('/billing/cost-items/cost', expect.objectContaining({ amount: 700 })));
    }
  });

  it('GETs the saved owner share after successful generation without posting it as tenant debt', async () => {
    let generated = false;
    const requests = [];
    lists['/billing/cost-items'][0].amount = 170;
    mocks.get.mockImplementation(path => {
      if (path === '/billing/periods/period') {
        requests.push('GET owner');
        return Promise.resolve(generated ? ownerPeriod() : { ...period, owner_cost_share: null });
      }
      return read(path);
    });
    mocks.post.mockImplementation(async path => {
      requests.push(`POST ${path}`);
      generated = true;
      lists['/billing/statements'] = [{ id: 'generated', billing_period_id: 'period', total_cost: 50, balance: 50 }];
      return structuredClone(lists['/billing/statements']);
    });
    const { container } = render(<Statements />);
    await openPeriod();
    await screen.findByText('notCalculated');
    fireEvent.click(screen.getByRole('button', { name: 'generate' }));
    await screen.findByText('snapshotHelp');
    expect(container.querySelector('.billing-owner-share .stats-grid')).toHaveTextContent('120,00');
    expect(requests.indexOf('POST /billing/periods/period/generate')).toBeLessThan(requests.lastIndexOf('GET owner'));
    expect(mocks.post).toHaveBeenCalledTimes(1);
    expect(mocks.post).toHaveBeenCalledWith('/billing/periods/period/generate', {});
  });
});
