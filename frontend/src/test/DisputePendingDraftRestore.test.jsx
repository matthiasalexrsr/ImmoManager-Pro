import { useRef, useState } from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import useFormDraft from '../hooks/useFormDraft';
import { openCommand, readPreview } from '../features/billingDisputes/disputeModel';
import { originalStatement, preview } from './fixtures/disputes';

const mocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), del: vi.fn() }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'actor', role: 'eigentuemer', portfolio_access: 'all' } }) }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key }) }));

const fields = ['period_id', 'case_id', 'command_json', 'review_json'].map(key => ({ key, type: 'text' }));
const schema = JSON.stringify(fields.map(row => [row.key, row.type]).sort((a, b) => a[0].localeCompare(b[0])));
const initial = { period_id: 'period', case_id: '', command_json: JSON.stringify(openCommand('period', originalStatement, 'tenant_statement', 'new-unused-key')), review_json: '' };
const confirmed = readPreview(preview({ ...openCommand('period', originalStatement, 'tenant_statement', 'retained-original-key'), reason: 'Original input', received_on: '2026-10-01' }),
  { ...openCommand('period', originalStatement, 'tenant_statement', 'retained-original-key'), reason: 'Original input', received_on: '2026-10-01' });
const restoredValues = { period_id: 'period', case_id: '', command_json: JSON.stringify(confirmed.command), review_json: JSON.stringify(confirmed.review) };
const stamp = { revision: '00000000-0000-4000-8000-000000000001', updated_at: '2026-10-03T12:00:00Z', expires_at: '2026-10-10T12:00:00Z' };
const stored = { ...stamp, schema, values: restoredValues, original_values: initial, edit_revision: null, submission_pending: true };

function useActualCore() {
  const [values, setValues] = useState(initial); const original = useRef(initial); const editRevision = useRef(null);
  const draft = useFormDraft({ config: { collection: 'billing/disputes', formKey: 'open:period' }, fields, values, original, editRevision,
    onRestore: row => { original.current = row.original_values; setValues(row.values); } });
  return { draft, values };
}

beforeEach(() => {
  vi.clearAllMocks(); mocks.get.mockResolvedValue({ draft: structuredClone(stored) }); mocks.put.mockResolvedValue(stamp);
});

describe('actual common draft core after journal reload', () => {
  it('retains the durable pending flag past the real 650 ms autosave interval after explicit restore', async () => {
    const { result } = renderHook(useActualCore);
    await waitFor(() => expect(result.current.draft.status).toBe('available'));
    await act(async () => { expect(await result.current.draft.restore()).toBe(true); });
    expect(result.current.values).toEqual(restoredValues);
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 850)); });
    expect(mocks.put).not.toHaveBeenCalled();
    expect(result.current.draft.draft.submission_pending).toBe(true);
    expect(JSON.parse(result.current.values.command_json)).toEqual(confirmed.command);
  });
  it('lets an explicitly chosen generic resume clear pending while keeping all exact command and review bytes', async () => {
    const { result } = renderHook(useActualCore);
    await waitFor(() => expect(result.current.draft.status).toBe('available'));
    await act(async () => { await result.current.draft.restore(); });
    await act(async () => { expect(await result.current.draft.resume()).toBe(true); });
    expect(mocks.put).toHaveBeenCalledTimes(1);
    expect(mocks.put.mock.calls[0][1]).toMatchObject({ submission_pending: false, values: restoredValues, original_values: initial });
  });
});
