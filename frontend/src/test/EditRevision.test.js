import { beforeEach, expect, it, vi } from 'vitest';
import { annotateRevisions, bindEditRevision, conditionalHeaders, EDIT_REVISION, revisionOptions, revisionResource, revisionSource, snapshotRevision } from '../editRevision';

beforeEach(() => { localStorage.clear(); vi.resetModules(); vi.restoreAllMocks(); });
const old = () => ({ id: 'record-1', name: 'Original', updated_at: '2026-10-01T08:30:40.123456' });
function response(data, status = 200, etag = null) {
  return { status, ok: status >= 200 && status < 300, json: async () => data, headers: { get: () => etag } };
}

it('preserves all server microseconds and does not serialize revision metadata', () => {
  const record = annotateRevisions(old(), '/properties');
  expect(Object.keys(record)).toEqual(['id', 'name', 'updated_at']);
  const payload = bindEditRevision({ name: 'Draft' }, snapshotRevision(record));
  const transformed = { ...payload, status: 'active' };
  expect(transformed[EDIT_REVISION]).toBe(payload[EDIT_REVISION]);
  expect(JSON.stringify(transformed)).toBe('{"name":"Draft","status":"active"}');
  expect(conditionalHeaders('/properties/record-1', transformed)['If-Match']).toContain('08:30:40.123456');
});

it('a later GET for the same ID cannot replace the old form or deletion snapshot', async () => {
  global.fetch = vi.fn().mockResolvedValueOnce(response(old()))
    .mockResolvedValueOnce(response({ ...old(), name: 'Server A', updated_at: '2026-10-01T08:30:40.987654' }))
    .mockResolvedValueOnce(response(old()));
  const { api } = await import('../api');
  const first = await api.get('/properties/record-1');
  await api.get('/properties/record-1');
  const draft = bindEditRevision({ name: 'Draft B' }, snapshotRevision(first));
  await api.put('/properties/record-1', { ...draft });
  expect(fetch.mock.calls[2][1].headers['If-Match']).toContain('.123456');
  expect(fetch.mock.calls[2][1].body).toBe('{"name":"Draft B"}');
});

it('uses authoritative single-record ETags and record-local list revisions', async () => {
  const authoritative = '"immo-v1:properties:record-1:2026-10-01T08:30:40.123456Z"';
  global.fetch = vi.fn().mockResolvedValueOnce(response(old(), 200, authoritative))
    .mockResolvedValueOnce(response([old(), { ...old(), id: 'record-2' }]))
    .mockResolvedValueOnce(response(null, 204)).mockResolvedValueOnce(response(old()));
  const { api } = await import('../api');
  const one = await api.get('/properties/record-1');
  const list = await api.getAll('/properties');
  await api.del('/properties/record-1', api.versionOptions(one));
  await api.patch('/properties/record-2', { name: 'Changed' }, api.versionOptions(list[1]));
  expect(fetch.mock.calls[2][1].headers['If-Match']).toBe(authoritative);
  expect(fetch.mock.calls[3][1].headers['If-Match']).toContain(':record-2:');
});

it('does not apply edit conditions to new records or payment commands', async () => {
  global.fetch = vi.fn().mockResolvedValue(response(old()));
  const { api } = await import('../api');
  const draft = bindEditRevision({ name: 'Create' }, snapshotRevision(old()));
  await api.post('/properties', draft);
  await api.post('/rent-charges/record-1/payments', draft);
  await api.put('/properties/record-1', { name: 'Legacy compatibility' });
  fetch.mock.calls.forEach(call => expect(call[1].headers).not.toHaveProperty('If-Match'));
});

it('reconciled financial forms use the current receipt-managed fields without serializing metadata', () => {
  const previous = { ...old(), amount_paid: 0, status: 'open' };
  const current = annotateRevisions({ ...previous, amount_paid: 40, status: 'partial', updated_at: '2026-10-01T09:00:00.123456' }, '/rent-charges');
  const draft = bindEditRevision({ cold_rent: 100 }, snapshotRevision(current));
  const source = revisionSource(draft, previous);
  expect(source.amount_paid).toBe(40);
  expect(source.status).toBe('partial');
  expect(JSON.stringify({ ...draft, amount_paid: source.amount_paid, status: source.status }))
    .toBe('{"cold_rent":100,"amount_paid":40,"status":"partial"}');
  expect(conditionalHeaders('/rent-charges/record-1', draft)['If-Match']).toContain('09:00:00.123456');
});

it('rejects snapshots of another resource before sending a write', () => {
  const record = annotateRevisions(old(), '/properties');
  expect(() => conditionalHeaders('/properties/other-id', null, revisionOptions(record))).toThrow(/anderen Datensatz/);
  expect(() => conditionalHeaders('/tenants/record-1', null, revisionOptions(record))).toThrow(/anderen Datensatz/);
});

it('recognizes nested meter resources while excluding commands', () => {
  expect(revisionResource('/handover-protocols/handover/meter-readings/reading')).toEqual({ collection: 'handover-protocols/meter-readings', id: 'reading' });
  expect(revisionResource('/meters/readings/all?limit=10')).toEqual({ collection: 'meters/readings', id: null });
  expect(revisionResource('/billing/periods/period/finalize')).toBeNull();
});

it('marks only 412 as an edit conflict and identifies the record to reconcile', async () => {
  global.fetch = vi.fn().mockResolvedValueOnce(response({ error: { code: 'EDIT_CONFLICT', message: 'Changed' } }, 412))
    .mockResolvedValueOnce(response({ error: { code: 'CONFLICT', message: 'Duplicate' } }, 409));
  const { api } = await import('../api');
  await expect(api.patch('/properties/record-1', {})).rejects.toMatchObject({ statusCode: 412, isEditConflict: true, resourcePath: '/properties/record-1' });
  await expect(api.patch('/properties/record-1', {})).rejects.toMatchObject({ statusCode: 409, isEditConflict: false });
});
