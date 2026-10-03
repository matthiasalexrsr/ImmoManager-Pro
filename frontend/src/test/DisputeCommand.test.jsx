import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import useDisputeCommand from '../features/billingDisputes/useDisputeCommand';
import { appendCommand, openCommand } from '../features/billingDisputes/disputeModel';
import { caseRow, originalStatement, preview } from './fixtures/disputes';

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), stored: null }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'actor', role: 'eigentuemer', portfolio_access: 'all' } }) }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key }) }));
const copy = value => structuredClone(value);
const stamp = { revision: '00000000-0000-4000-8000-000000000001', updated_at: '2026-10-03T12:00:00Z', expires_at: '2026-10-10T12:00:00Z' };
const failure = (statusCode, message = 'Synthetic failure') => Object.assign(new Error(message), { statusCode });
const pending = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
function controller(extra = {}) {
  return renderHook(() => useDisputeCommand({ periodId: 'period', initialCommand: openCommand('period', originalStatement, 'tenant_statement', 'retained-key'), ...extra }));
}
async function prepare(result, caseId = '') {
  await waitFor(() => expect(result.current.enabled).toBe(true));
  act(() => result.current.change({ reason: 'Unchanged reason', [caseId ? 'observed_on' : 'received_on']: '2026-10-01' }));
  await act(async () => { await result.current.preview(); });
  expect(result.current.phase).toBe('review');
}
beforeEach(() => {
  vi.clearAllMocks(); mocks.stored = null;
  mocks.get.mockImplementation(() => Promise.resolve({ draft: copy(mocks.stored) }));
  mocks.put.mockImplementation((_path, data) => { mocks.stored = { ...copy(data), ...stamp }; return Promise.resolve(stamp); });
  mocks.del.mockResolvedValue({ discarded: true });
  mocks.post.mockImplementation((path, command) => path.endsWith('/preview') ? Promise.resolve(path.includes('/case/') ? { ...preview(command), binding: copy(caseRow) } : preview(command))
    : Promise.resolve({ case_id: 'case', event_id: 'event', revision: command.expected_revision ? command.expected_revision + 1 : 1 }));
});

describe('exact journal commands with the actual common encrypted draft hook', () => {
  it('persists the complete reviewed command as pending before sending one domain POST', async () => {
    const saved = vi.fn(), close = vi.fn(); const { result } = controller({ onSaved: saved, onClose: close }); await prepare(result);
    const durable = pending(); mocks.put.mockReturnValueOnce(durable.promise);
    let operation; act(() => { operation = result.current.confirm(); });
    await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(1));
    expect(mocks.post).toHaveBeenCalledTimes(1);
    const payload = mocks.put.mock.calls[0][1];
    expect(payload).toMatchObject({ collection: 'billing/disputes', entity_id: null, form_key: 'open:period', submission_pending: true });
    const exact = JSON.parse(payload.values.command_json);
    expect(exact).toMatchObject({ idempotency_key: 'retained-key', reason: 'Unchanged reason', expected_statement_revision: 3, preview_hash: 'd'.repeat(64) });
    await act(async () => { durable.resolve(stamp); await operation; });
    expect(mocks.post.mock.calls[1][1]).toEqual(exact); expect(saved).toHaveBeenCalledTimes(1); expect(close).toHaveBeenCalledTimes(1);
  });
  it('restores a lost-response command and retries its same key, revision and preview hash without a new preview', async () => {
    const first = controller(); await prepare(first.result);
    mocks.post.mockRejectedValueOnce(new Error('Response lost'));
    await act(async () => { await first.result.current.confirm(); });
    expect(first.result.current.phase).toBe('unknown'); expect(mocks.stored.submission_pending).toBe(true);
    const original = copy(mocks.post.mock.calls[1][1]); first.unmount();
    const second = controller({ initialCommand: openCommand('period', originalStatement, 'tenant_statement', 'must-never-be-sent') });
    await waitFor(() => expect(second.result.current.draft.status).toBe('available'));
    await act(async () => { await second.result.current.draft.restore(); });
    expect(second.result.current.phase).toBe('unknown');
    act(() => second.result.current.change({ reason: 'Must stay unchanged' })); expect(second.result.current.command).toEqual(original);
    await act(async () => { await second.result.current.confirm(); });
    expect(mocks.post).toHaveBeenCalledTimes(3); expect(mocks.post.mock.calls[2][1]).toEqual(original);
    expect(mocks.post.mock.calls.filter(([path]) => path.endsWith('/preview'))).toHaveLength(1);
  });
  it('keeps inputs and the original case revision after a known 412 rejection', async () => {
    const { result } = controller({ caseId: 'case', initialCommand: appendCommand(caseRow, 'note', 'event-key') }); await prepare(result, 'case');
    mocks.post.mockRejectedValueOnce(failure(412)); await act(async () => { await result.current.confirm(); });
    expect(result.current.phase).toBe('conflict'); expect(result.current.command).toMatchObject({ idempotency_key: 'event-key', expected_revision: 27, reason: 'Unchanged reason', observed_on: '2026-10-01' });
    expect(mocks.stored.submission_pending).toBe(false);
    act(() => result.current.change({ reason: 'Reviewed input' })); expect(result.current.command.expected_revision).toBe(27);
  });
  it('blocks domain confirmation when saving its prepared encrypted draft fails', async () => {
    const { result } = controller(); await prepare(result);
    mocks.put.mockRejectedValueOnce(failure(503, 'Draft unavailable')); await act(async () => { await result.current.confirm(); });
    expect(mocks.post).toHaveBeenCalledTimes(1); expect(result.current.phase).toBe('review');
    expect(result.current.command.reason).toBe('Unchanged reason'); expect(result.current.draft.error).toBe('Draft unavailable');
  });
  it('retries only cleanup after a confirmed domain receipt', async () => {
    const saved = vi.fn(), close = vi.fn(); const { result } = controller({ onSaved: saved, onClose: close }); await prepare(result);
    mocks.del.mockRejectedValueOnce(failure(503, 'Cleanup unavailable')); await act(async () => { await result.current.confirm(); });
    expect(result.current.phase).toBe('saved'); expect(saved).toHaveBeenCalledTimes(1); expect(close).not.toHaveBeenCalled();
    await act(async () => { await result.current.confirm(); await result.current.cleanup(); });
    expect(mocks.post).toHaveBeenCalledTimes(2); expect(mocks.del).toHaveBeenCalledTimes(2); expect(saved).toHaveBeenCalledTimes(1); expect(close).toHaveBeenCalledTimes(1);
  });
  it('aborts its pending operation on context unmount and sends no domain command after late draft persistence', async () => {
    const current = controller(); await prepare(current.result); const durable = pending(); mocks.put.mockReturnValueOnce(durable.promise);
    let operation; act(() => { operation = current.result.current.confirm(); }); await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(1));
    current.unmount(); await act(async () => { durable.resolve(stamp); await operation; });
    expect(mocks.post).toHaveBeenCalledTimes(1); expect(mocks.del).not.toHaveBeenCalled();
  });
  it('rejects a preview that alters the request and preserves the entered reason', async () => {
    const { result } = controller(); await waitFor(() => expect(result.current.enabled).toBe(true));
    act(() => result.current.change({ reason: 'Original input', received_on: '2026-10-01' }));
    mocks.post.mockImplementationOnce((_path, command) => Promise.resolve(preview({ ...command, reason: 'Changed by response' })));
    await act(async () => { await result.current.preview(); });
    expect(result.current.error.message).toBe('invalidDisputeResponse'); expect(result.current.phase).toBe('editing'); expect(result.current.command.reason).toBe('Original input');
    expect(mocks.put).not.toHaveBeenCalled();
  });
  it('retains a known 409 preview conflict without silently adopting another revision', async () => {
    const { result } = controller(); await waitFor(() => expect(result.current.enabled).toBe(true));
    act(() => result.current.change({ reason: 'Original input', received_on: '2026-10-01' })); mocks.post.mockRejectedValueOnce(failure(409));
    await act(async () => { await result.current.preview(); });
    expect(result.current.phase).toBe('conflict'); expect(result.current.command).toMatchObject({ idempotency_key: 'retained-key', expected_statement_revision: 3, reason: 'Original input' });
  });
});
