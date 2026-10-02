import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import RentBatchPanel from '../components/RentBatchPanel';
import RentGenerationModal from '../components/RentGenerationModal';

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), role: 'eigentuemer' }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'owner', role: mocks.role }, role: mocks.role }) }));
const translate = key => key.split('.').at(-1);
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: translate, locale: 'de-DE' }) }));

const base = { id: 'batch-one', state: 'preparing', phase: 'contracts', cursor: 'c0', revision: 0,
  parameters: { start_month: '2026-10', end_month: '2027-01' }, persistent: true,
  contract_count: 0, price_count: 0, created_count: 0, existing_count: 0, examined_count: 0 };
const ready = { ...base, state: 'ready', phase: 'seal', plan_hash: 'a'.repeat(64), cursor: 'ready', revision: 4,
  contract_count: 1, sealed_at: '2026-10-01T10:00:00' };
const complete = { ...ready, state: 'done', created_count: 4, examined_count: 4, cursor: 'done', revision: 8 };
const preview = { items: [{ contract_id: 'one', contract_number: 'V-1', month: '2026-10', total_amount: 950 }],
  plan_hash: ready.plan_hash, has_more: false, next_cursor: null };
const submit = () => fireEvent.submit(screen.getByRole('dialog').querySelector('form'));
function deferred() { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; }
beforeEach(() => { mocks.get.mockReset().mockResolvedValue(preview); mocks.post.mockReset(); mocks.role = 'eigentuemer'; localStorage.clear(); });

describe('Durable rent workflow controls', () => {
  it('creates no charges during preparation and requires explicit plan confirmation', async () => {
    const generated = vi.fn();
    mocks.post.mockResolvedValueOnce(ready);
    render(<RentBatchPanel initialBatch={base} onGenerated={generated} onClose={vi.fn()} />);
    submit();
    await screen.findByRole('button', { name: 'confirm' });
    await screen.findByText('V-1');
    expect(mocks.post).toHaveBeenCalledTimes(1);
    expect(mocks.post.mock.calls[0][0]).toMatch(/\/advance$/);
    expect(generated).not.toHaveBeenCalled();
    mocks.post.mockResolvedValueOnce({ ...ready, state: 'running', cursor: 'running' }).mockResolvedValueOnce(complete);
    submit();
    await screen.findByRole('button', { name: 'finish' });
    expect(mocks.post.mock.calls[1]).toEqual(['/rent-charges/batches/batch-one/confirm', { cursor: 'ready', plan_hash: ready.plan_hash }]);
    expect(generated).not.toHaveBeenCalled();
    submit();
    await waitFor(() => expect(generated).toHaveBeenCalledWith({ created_count: 4, skipped_count: 0, batch_id: 'batch-one' }));
  });

  it('waits for an in-flight step before pausing with its new committed cursor', async () => {
    const pending = deferred();
    mocks.post.mockReturnValueOnce(pending.promise).mockResolvedValueOnce({ ...base, state: 'paused', cursor: 'c2', revision: 2 });
    render(<RentBatchPanel initialBatch={base} onClose={vi.fn()} />);
    submit(); await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole('button', { name: 'pause' }));
    expect(mocks.post).toHaveBeenCalledTimes(1);
    await act(async () => pending.resolve({ ...base, cursor: 'c1', revision: 1 }));
    await screen.findByRole('button', { name: 'resume' });
    expect(mocks.post.mock.calls[1]).toEqual(['/rent-charges/batches/batch-one/pause', { cursor: 'c1' }]);
  });

  it('reloads server truth after a lost response and does not blindly replay that POST', async () => {
    mocks.post.mockRejectedValueOnce(new Error('connection lost after commit'));
    mocks.get.mockImplementation(path => Promise.resolve(path.includes('/preview?') ? preview : ready));
    render(<RentBatchPanel initialBatch={base} onClose={vi.fn()} />);
    submit(); await screen.findByRole('alert');
    expect(screen.getByRole('button', { name: 'continue' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'refresh' }));
    await screen.findByText('V-1');
    expect(screen.getByRole('button', { name: 'confirm' })).toBeEnabled();
    expect(mocks.post).toHaveBeenCalledTimes(1);
    expect(mocks.get).toHaveBeenCalledWith('/rent-charges/batches/batch-one');
  });

  it('aborts on closing and cannot revive a pending loop after revoked and renewed permissions', async () => {
    const pending = deferred(); mocks.post.mockReturnValue(pending.promise);
    const closed = vi.fn();
    const view = render(<RentBatchPanel initialBatch={base} onClose={closed} />);
    submit(); await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    const signal = mocks.post.mock.calls[0][2].signal;
    mocks.role = 'readonly'; view.rerender(<RentBatchPanel initialBatch={base} onClose={closed} />);
    expect(closed).toHaveBeenCalled();
    mocks.role = 'eigentuemer'; view.rerender(<RentBatchPanel initialBatch={base} onClose={closed} />);
    await act(async () => pending.resolve({ ...base, cursor: 'c1', revision: 1 }));
    expect(mocks.post).toHaveBeenCalledTimes(1);
    view.unmount(); expect(signal.aborted).toBe(true);
  });

  it('preserves a create idempotency key after an unknown outcome and accepts legacy handoff', async () => {
    mocks.post.mockRejectedValueOnce(new Error('connection lost')).mockResolvedValueOnce(base);
    render(<RentGenerationModal contracts={[]} onGenerated={vi.fn()} onClose={vi.fn()} />);
    fireEvent.click(screen.getByLabelText('saveWorkflow'));
    submit(); await screen.findByRole('alert');
    submit(); await screen.findByRole('button', { name: 'continue' });
    expect(mocks.post.mock.calls[0][0]).toBe('/rent-charges/batches');
    expect(mocks.post.mock.calls[1][1].idempotency_key).toBe(mocks.post.mock.calls[0][1].idempotency_key);
    expect(localStorage.getItem('immo.rent-batch.owner')).toBe('batch-one');
  });

  it('restores the user-owned stored ID and server history rather than keeping a stale client cursor', async () => {
    localStorage.setItem('immo.rent-batch.owner', 'batch-one');
    mocks.get.mockResolvedValueOnce(base);
    render(<RentGenerationModal contracts={[]} onGenerated={vi.fn()} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'restore' }));
    await screen.findByRole('button', { name: 'continue' });
    expect(mocks.get).toHaveBeenCalledWith('/rent-charges/batches/batch-one');
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('keeps the dialog open when a legacy confirmation safely delegates changed-size work', async () => {
    const closed = vi.fn();
    mocks.post.mockResolvedValueOnce({ policy: 'full_month', preview_hash: 'legacy', total_amount: 950,
      candidates: preview.items, existing: [], skipped_contracts: [] }).mockResolvedValueOnce({ policy: 'durable_batch', batch: base });
    render(<RentGenerationModal contracts={[]} onGenerated={vi.fn()} onClose={closed} />);
    submit(); await screen.findByRole('button', { name: 'generate' });
    submit(); await screen.findByRole('button', { name: 'continue' });
    expect(closed).not.toHaveBeenCalled();
    expect(screen.getAllByRole('dialog')).toHaveLength(1);
  });
});
