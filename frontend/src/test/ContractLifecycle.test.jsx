import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { StrictMode, useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import userEvent from '@testing-library/user-event';
import ContractLifecycle from '../components/ContractLifecycle';
import { bindEditRevision } from '../editRevision';
import de from '../../../i18n/de-DE.json';
import en from '../../../i18n/en-US.json';
import es from '../../../i18n/es-ES.json';

const mocks = vi.hoisted(() => ({
  get: vi.fn(), post: vi.fn(), confirm: vi.fn(), canWrite: true, locale: 'de-DE',
  auth: { id: 'actor-1', role: 'verwalter', write_permissions: ['rental'],
    portfolio_access: 'selected', portfolio_ids: ['portfolio-1'], is_active: true },
  drafts: [], history: [], sourceEtag: '"immo-contract-etag-1"', byId: new Map(),
}));
vi.mock('../api', () => ({ api: { get: mocks.get, post: mocks.post } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({
  user: mocks.auth, role: mocks.auth?.role, canWrite: () => mocks.canWrite,
}) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => mocks.confirm }));
const languages = { 'de-DE': de, 'en-US': en, 'es-ES': es };
const translate = (key, params) => {
  let value = key.split('.').reduce((node, part) => node?.[part], languages[mocks.locale]) || key;
  if (params && typeof value === 'string') for (const [name, replacement] of Object.entries(params)) {
    value = value.replaceAll(`{{${name}}}`, String(replacement));
  }
  return value;
};
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: mocks.locale, t: translate }) }));

const contract = {
  id: 'contract-1', contract_number: 'MV-OLD', property_id: 'property-1',
  unit_id: 'unit-1', tenant_id: 'tenant-1', start_date: '2025-01-01',
  end_date: '2026-12-31', status: 'active', updated_at: '2026-10-01T10:00:00',
};
const sourceRecord = () => {
  const row = { ...contract, updated_at: '2026-10-01T10:00:00' };
  return bindEditRevision(row, Object.freeze({
    collection: 'contracts', id: row.id, updatedAt: row.updated_at,
    path: `/contracts/${row.id}`, etag: mocks.sourceEtag, source: Object.freeze({ ...row }),
  }));
};
const obligations = {
  rent_charge_count: 3, receivable_count: 2, receivables_due_after_end_count: 1,
  receivables_due_after_end_sample: [{ id: 'recv-1', due_date: '2027-01-10',
    description: 'Synthetic receivable', amount_due: '125.00', amount_paid: '25.00' }],
  rent_period_conflict_count: 1, rent_period_conflict_sample: [{ id: 'charge-1', month: '2027-01' }],
  snapshot_sha256: 'b'.repeat(64), policy: 'keep_all_obligations_unchanged;due_date_is_not_service_period',
};
const renewalData = { operation: 'renewal', reason: 'Reviewed successor terms',
  new_contract_number: 'MV-NEW', new_start_date: '2027-01-01', new_end_date: null };
const terminationData = { operation: 'termination', reason: 'Synthetic termination reason',
  termination_end_date: '2026-11-30' };
const reviewOf = data => ({
  source_contract: { ...contract }, source_contract_etag: mocks.sourceEtag,
  related_etags: { property: '"p"', unit: '"u"', tenant: '"t"' },
  proposed_contract: data.operation === 'renewal'
    ? { contract_number: data.new_contract_number, start_date: data.new_start_date, end_date: data.new_end_date }
    : { end_date: data.termination_end_date, status_policy: 'active_through_inclusive_end' },
  data, obligations: structuredClone(obligations), supersedes: null,
  date_policy: 'inclusive_end;manual_finalize_after_end;server_utc_date',
  notice_policy: 'manual_management_only;no_delivery_or_legal_validity_asserted',
});
function draft(overrides = {}) {
  const data = overrides.data || renewalData;
  return {
    id: 'draft-1', contract_id: contract.id, portfolio_id: 'portfolio-1',
    property_id: contract.property_id, unit_id: contract.unit_id, tenant_id: contract.tenant_id,
    actor_id: 'actor-1', revision: '11111111-1111-1111-1111-111111111111',
    state: 'draft', data: structuredClone(data), source_contract_etag: mocks.sourceEtag,
    review: null, review_hash: null, applied_contract_etag: null,
    finalized_contract_etag: null, successor_contract_id: null,
    superseded_by_draft_id: null, supersedes_draft_id: null,
    created_at: '2026-10-01T10:00:00+00:00', updated_at: '2026-10-01T10:00:00+00:00',
    persistent: true, ...overrides,
  };
}
function reviewed(overrides = {}) {
  const data = overrides.data || renewalData;
  return draft({ state: 'reviewed', data, review: reviewOf(data), review_hash: 'a'.repeat(64),
    revision: '22222222-2222-2222-2222-222222222222',
    ...(['confirmed', 'pending_effective', 'completed', 'superseded'].includes(overrides.state)
      ? { applied_contract_etag: '"applied"', successor_contract_id: data.operation === 'renewal' ? 'successor-1' : null } : {}),
    ...overrides });
}
function historyItem(result, overrides = {}) {
  return { id: `history-${result.id}`, draft_id: result.id, actor_id: result.actor_id,
    operation: result.state === 'completed' ? 'finalize' : 'confirm',
    created_at: '2026-10-02T10:00:00+00:00', result: structuredClone(result),
    current_state: result.state, supersedes_draft_id: result.supersedes_draft_id,
    superseded_by_draft_id: result.superseded_by_draft_id, ...overrides };
}
const page = (items, next_before = null) => ({ items: structuredClone(items), next_before, persistent: true });
const pending = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };

function installApi() {
  mocks.get.mockImplementation(async path => {
    if (path === '/contracts/contract-1') return sourceRecord();
    if (path.startsWith('/contracts/contract-1/lifecycle/drafts?')) return page(mocks.drafts);
    if (path.startsWith('/contracts/contract-1/lifecycle/history?')) return page(mocks.history);
    const match = path.match(/\/lifecycle\/drafts\/([^/?]+)$/);
    if (match) return structuredClone(mocks.byId.get(decodeURIComponent(match[1])) || mocks.drafts.find(item => item.id === decodeURIComponent(match[1])));
    throw new Error(`Unexpected GET ${path}`);
  });
  mocks.post.mockImplementation(async (path, body) => {
    let result;
    if (path.endsWith('/drafts')) result = draft({ data: body.data });
    else if (path.endsWith('/edit')) result = draft({ id: path.split('/').at(-2), data: body.data,
      revision: '33333333-3333-3333-3333-333333333333' });
    else if (path.endsWith('/review')) result = reviewed({ id: path.split('/').at(-2),
      data: (mocks.byId.get(path.split('/').at(-2)) || mocks.drafts[0] || draft()).data });
    else if (path.endsWith('/confirm')) {
      const current = mocks.byId.get(path.split('/').at(-2)) || mocks.drafts[0] || reviewed();
      result = { ...structuredClone(current), state: current.data.operation === 'termination' ? 'pending_effective' : 'confirmed',
        review_hash: current.review_hash || 'a'.repeat(64), review: current.review || reviewOf(current.data),
        applied_contract_etag: '"applied"',
        successor_contract_id: current.data.operation === 'renewal' ? 'successor-1' : null,
        revision: '44444444-4444-4444-4444-444444444444' };
    } else if (path.endsWith('/finalize')) {
      const current = mocks.byId.get(path.split('/').at(-2));
      result = { ...structuredClone(current), state: 'completed', current_state: 'completed',
        finalized_contract_etag: '"final"', revision: '55555555-5555-5555-5555-555555555555' };
    } else throw new Error(`Unexpected POST ${path}`);
    mocks.byId.set(result.id, structuredClone(result));
    if (path.endsWith('/confirm') || path.endsWith('/finalize')) {
      // Historical results never change. Only today's state/link metadata does.
      mocks.history = mocks.history.map(item => item.draft_id === result.id
        ? { ...item, current_state: result.state, superseded_by_draft_id: result.superseded_by_draft_id }
        : item);
      mocks.history.unshift(historyItem(result, { id: `history-${result.id}-${result.state}` }));
      mocks.drafts = mocks.drafts.filter(item => item.id !== result.id);
    } else {
      mocks.drafts = [...mocks.drafts.filter(item => item.id !== result.id), result];
    }
    return result;
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.canWrite = true; mocks.locale = 'de-DE'; mocks.sourceEtag = '"immo-contract-etag-1"';
  mocks.auth = { id: 'actor-1', role: 'verwalter', write_permissions: ['rental'],
    portfolio_access: 'selected', portfolio_ids: ['portfolio-1'], is_active: true };
  mocks.drafts = []; mocks.history = []; mocks.byId = new Map();
  mocks.confirm.mockResolvedValue(true);
  let key = 0;
  vi.stubGlobal('crypto', { randomUUID: () => `00000000-0000-4000-8000-${String(++key).padStart(12, '0')}` });
  installApi();
});

function mount(props = {}) {
  return render(<ContractLifecycle contract={contract} opener={props.opener || null}
    onClose={props.onClose || vi.fn()} onChanged={props.onChanged || vi.fn()} />);
}
async function ready() {
  await screen.findByRole('heading', { name: de.contractLifecycle.title });
  await waitFor(() => expect(screen.queryByText(de.contractLifecycle.loading)).not.toBeInTheDocument());
}
async function fillRenewal({ unlimited = true } = {}) {
  fireEvent.change(screen.getByLabelText(de.contractLifecycle.reason), { target: { value: 'Reviewed new terms' } });
  fireEvent.change(screen.getByLabelText(de.contractLifecycle.newNumber), { target: { value: 'MV-2027' } });
  fireEvent.change(screen.getByLabelText(de.contractLifecycle.newStart), { target: { value: '2027-01-01' } });
  if (unlimited) fireEvent.click(screen.getByLabelText(de.contractLifecycle.deliberateUnlimited));
  else fireEvent.change(screen.getByLabelText(de.contractLifecycle.newEnd), { target: { value: '2028-12-31' } });
}

describe('contract lifecycle dialog', () => {
  it('creates an open-ended renewal with a fresh strong ETag and bounded page reads', async () => {
    mount(); await ready(); await fillRenewal();
    fireEvent.click(screen.getByRole('button', { name: de.contractLifecycle.saveDraft }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalled());
    const [path, payload] = mocks.post.mock.calls[0];
    expect(path).toBe('/contracts/contract-1/lifecycle/drafts');
    expect(payload.expected_contract_etag).toBe('"immo-contract-etag-1"');
    expect(payload.idempotency_key).toMatch(/^g06:/);
    expect(payload.data).toEqual({
      operation: 'renewal', reason: 'Reviewed new terms', new_contract_number: 'MV-2027',
      new_start_date: '2027-01-01', new_end_date: null,
    });
    const initialReads = mocks.get.mock.calls.map(call => call[0]);
    expect(initialReads).toContain('/contracts/contract-1/lifecycle/drafts?limit=25');
    expect(initialReads).toContain('/contracts/contract-1/lifecycle/history?limit=25');
  });

  it('retries an unknown outcome with the exact same payload/key and never substitutes a newer ETag', async () => {
    mount(); await ready(); await fillRenewal();
    mocks.post.mockRejectedValueOnce(Object.assign(new Error('Synthetic lost response'), { isNetwork: true }));
    fireEvent.click(screen.getByRole('button', { name: de.contractLifecycle.saveDraft }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Synthetic lost response');
    const first = mocks.post.mock.calls[0];
    mocks.sourceEtag = '"new-etag-that-must-not-enter-old-command"';
    fireEvent.click(screen.getByRole('button', { name: de.contractLifecycle.retryExact }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    expect(mocks.post.mock.calls[1][0]).toBe(first[0]);
    expect(mocks.post.mock.calls[1][1]).toBe(first[1]);
    expect(mocks.post.mock.calls[1][1].expected_contract_etag).toBe('"immo-contract-etag-1"');
    expect(mocks.post.mock.calls[1][1].idempotency_key).toBe(first[1].idempotency_key);
  });

  it.each([409, 412])('requires explicit reload/re-review after HTTP %s and offers no exact retry', async status => {
    mount(); await ready(); await fillRenewal();
    mocks.post.mockRejectedValueOnce(Object.assign(new Error('Synthetic stale contract'), { statusCode: status }));
    fireEvent.click(screen.getByRole('button', { name: de.contractLifecycle.saveDraft }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Synthetic stale contract');
    expect(screen.queryByRole('button', { name: de.contractLifecycle.retryExact })).not.toBeInTheDocument();
    const reload = screen.getByRole('button', { name: de.contractLifecycle.reloadReview });
    fireEvent.click(reload);
    await waitFor(() => expect(mocks.get.mock.calls.filter(([path]) => path === '/contracts/contract-1').length).toBeGreaterThan(1));
  });

  it('renders review obligations as readable facts and requires deliberate confirmation', async () => {
    const item = reviewed();
    mocks.drafts = [item]; mocks.byId.set(item.id, item);
    mount(); await ready();
    fireEvent.click(screen.getByRole('button', { name: new RegExp(de.contractLifecycle.renewal) }));
    expect(screen.getByText(de.contractLifecycle.reviewTitle)).toBeInTheDocument();
    expect(screen.getByText('3 Mietforderungen')).toBeInTheDocument();
    expect(screen.getByText('1 Forderungen nach Mietende')).toBeInTheDocument();
    expect(screen.getByText('Synthetic receivable')).toBeInTheDocument();
    expect(screen.getByText(de.contractLifecycle.keepObligations)).toBeInTheDocument();
    expect(screen.queryByText(/"obligations"/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: de.contractLifecycle.confirm }));
    expect(await screen.findByRole('alert')).toHaveTextContent(de.contractLifecycle.confirmRequired);
    expect(mocks.confirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText(de.contractLifecycle.confirmChecked));
    fireEvent.click(screen.getByRole('button', { name: de.contractLifecycle.confirm }));
    await waitFor(() => expect(mocks.confirm).toHaveBeenCalledWith(de.contractLifecycle.confirmPrompt));
    await waitFor(() => expect(mocks.post.mock.calls.some(([path]) => path.endsWith('/confirm'))).toBe(true));
    const [, body] = mocks.post.mock.calls.find(([path]) => path.endsWith('/confirm'));
    expect(body).toMatchObject({
      expected_revision: item.revision, reviewed_hash: 'a'.repeat(64), confirmed: true,
      expected_contract_etag: '"immo-contract-etag-1"',
    });
  });

  it('suppresses a late confirmation when actor grants change during the confirmation prompt', async () => {
    const item = reviewed();
    mocks.drafts = [item]; mocks.byId.set(item.id, item);
    const decision = pending(); mocks.confirm.mockReturnValue(decision.promise);
    const view = mount(); await ready();
    fireEvent.click(screen.getByRole('button', { name: new RegExp(de.contractLifecycle.renewal) }));
    fireEvent.click(screen.getByLabelText(de.contractLifecycle.confirmChecked));
    fireEvent.click(screen.getByRole('button', { name: de.contractLifecycle.confirm }));
    await waitFor(() => expect(mocks.confirm).toHaveBeenCalled());
    mocks.canWrite = false;
    mocks.auth = { ...mocks.auth, write_permissions: [] };
    view.rerender(<ContractLifecycle contract={contract} opener={null} onClose={vi.fn()} onChanged={vi.fn()} />);
    await act(async () => decision.resolve(true));
    expect(mocks.post.mock.calls.some(([path]) => path.endsWith('/confirm'))).toBe(false);
  });

  it('shows confirmed history to readonly without exposing write/finalize actions', async () => {
    mocks.canWrite = false; mocks.auth = { ...mocks.auth, role: 'readonly', write_permissions: [] };
    const result = reviewed({ state: 'pending_effective', data: terminationData,
      review: reviewOf(terminationData), review_hash: 'a'.repeat(64) });
    mocks.history = [historyItem(result, { current_state: 'pending_effective' })];
    mocks.byId.set(result.id, result);
    mount(); await ready();
    const card = screen.getByRole('button', { name: new RegExp(de.contractLifecycle.termination) });
    fireEvent.click(card);
    expect(screen.getByText(de.contractLifecycle.reviewTitle)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: de.contractLifecycle.finalize })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: de.contractLifecycle.saveDraft })).not.toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('finalizes a fresh pending termination created by another authorized actor and keeps that valid response', async () => {
    const current = reviewed({ state: 'pending_effective', actor_id: 'original-creator', data: terminationData,
      review: reviewOf(terminationData), review_hash: 'a'.repeat(64) });
    mocks.history = [historyItem(current, { current_state: 'pending_effective' })];
    mocks.byId.set(current.id, current);
    mount(); await ready();
    fireEvent.click(screen.getByRole('button', { name: de.contractLifecycle.historyTab }));
    fireEvent.click(screen.getByRole('button', { name: new RegExp(de.contractLifecycle.termination) }));
    mocks.sourceEtag = '"fresh-finalize-etag"';
    fireEvent.click(screen.getByRole('button', { name: de.contractLifecycle.finalize }));
    await waitFor(() => expect(mocks.confirm).toHaveBeenCalledWith(de.contractLifecycle.finalizePrompt));
    await waitFor(() => expect(mocks.post.mock.calls.some(([path]) => path.endsWith('/finalize'))).toBe(true));
    const [, payload] = mocks.post.mock.calls.find(([path]) => path.endsWith('/finalize'));
    expect(payload.expected_contract_etag).toBe('"fresh-finalize-etag"');
    expect(payload.expected_revision).toBe(current.revision);
    expect(payload.confirmed).toBe(true);
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    expect(mocks.byId.get(current.id).actor_id).toBe('original-creator');
    expect(mocks.byId.get(current.id).state).toBe('completed');
    await waitFor(() => expect(screen.queryByRole('button', { name: de.contractLifecycle.finalize })).not.toBeInTheDocument());
    expect(screen.getByRole('status')).toHaveTextContent(de.contractLifecycle.state_completed);
    expect(mocks.history.find(item => item.operation === 'confirm').result.state).toBe('pending_effective');
  });

  it('renders superseded predecessor/successor evidence and never offers finalize for superseded state', async () => {
    const predecessor = reviewed({ id: 'draft-old', state: 'pending_effective', data: terminationData,
      review: reviewOf(terminationData), review_hash: 'a'.repeat(64) });
    const successorData = { ...terminationData, reason: 'Corrected earlier end', termination_end_date: '2026-11-15' };
    const successor = reviewed({ id: 'draft-new', state: 'pending_effective', data: successorData,
      review: { ...reviewOf(successorData), supersedes: {
        id: 'draft-old', termination_end_date: terminationData.termination_end_date, review_hash: predecessor.review_hash,
      } }, review_hash: 'c'.repeat(64), supersedes_draft_id: 'draft-old' });
    mocks.byId.set('draft-old', { ...predecessor, state: 'superseded', superseded_by_draft_id: 'draft-new' });
    mocks.byId.set('draft-new', successor);
    mocks.history = [
      historyItem(predecessor, { current_state: 'superseded', superseded_by_draft_id: 'draft-new' }),
      historyItem(successor, { current_state: 'pending_effective', supersedes_draft_id: 'draft-old' }),
    ];
    mount(); await ready();
    fireEvent.click(screen.getByRole('button', { name: de.contractLifecycle.historyTab }));
    const cards = screen.getAllByRole('button', { name: new RegExp(de.contractLifecycle.termination) });
    fireEvent.click(cards[0]);
    expect(await screen.findByText(de.contractLifecycle.supersededTitle)).toBeInTheDocument();
    expect(screen.getByText(/draft-new/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: de.contractLifecycle.finalize })).not.toBeInTheDocument();

    fireEvent.click(cards[1]);
    expect(await screen.findByText(de.contractLifecycle.supersedesTitle)).toBeInTheDocument();
    expect(screen.getByText(/draft-old/)).toBeInTheDocument();
    expect(screen.getByText(/2026-11-30/)).toBeInTheDocument();
  });

  it('rejects a foreign/malformed success without false success and preserves exact retry', async () => {
    const changed = vi.fn(); mount({ onChanged: changed }); await ready(); await fillRenewal();
    mocks.post.mockResolvedValueOnce(draft({ contract_id: 'foreign-contract', data: {
      operation: 'renewal', reason: 'Reviewed new terms', new_contract_number: 'MV-2027',
      new_start_date: '2027-01-01', new_end_date: null,
    }}));
    fireEvent.click(screen.getByRole('button', { name: de.contractLifecycle.saveDraft }));
    expect(await screen.findByRole('alert')).toHaveTextContent(de.contractLifecycle.malformed);
    expect(changed).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: de.contractLifecycle.retryExact })).toBeInTheDocument();
  });

  it('uses keyset pages of 25 and appends only after an explicit load-more action', async () => {
    mocks.drafts = Array.from({ length: 25 }, (_, index) => draft({ id: `draft-${index}`,
      data: { ...renewalData, reason: `Reason ${index}` } }));
    mocks.get.mockImplementation(async path => {
      if (path === '/contracts/contract-1') return sourceRecord();
      if (path === '/contracts/contract-1/lifecycle/drafts?limit=25') return page(mocks.drafts, 'cursor-25');
      if (path === '/contracts/contract-1/lifecycle/drafts?limit=25&before=cursor-25') return page([
        draft({ id: 'draft-25', data: { ...renewalData, reason: 'Reason 25' } }),
      ]);
      if (path.startsWith('/contracts/contract-1/lifecycle/history?')) return page([]);
      throw new Error(`Unexpected GET ${path}`);
    });
    mount(); await ready();
    expect(screen.queryByText('Reason 25')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: de.contractLifecycle.loadMore }));
    expect(await screen.findByText('Reason 25')).toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledWith(
      '/contracts/contract-1/lifecycle/drafts?limit=25&before=cursor-25',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it('compares real API field values independently of JSON order and preserves the form across language changes', async () => {
    const data = { reason: renewalData.reason, operation: 'renewal', new_contract_number: 'MV-NEW',
      new_start_date: '2027-01-01', new_end_date: null };
    const item = reviewed({ data }); mocks.drafts = [item]; mocks.byId.set(item.id, item);
    const view = mount(); await ready();
    fireEvent.click(screen.getByRole('button', { name: new RegExp(de.contractLifecycle.renewal) }));
    expect(screen.getByRole('button', { name: de.contractLifecycle.confirm })).toBeEnabled();
    fireEvent.click(screen.getByLabelText(de.contractLifecycle.confirmChecked));
    fireEvent.change(screen.getByLabelText(de.contractLifecycle.reason), { target: { value: 'Unsaved local reason' } });
    expect(screen.getByRole('button', { name: de.contractLifecycle.confirm })).toBeDisabled();
    expect(screen.getByLabelText(de.contractLifecycle.confirmChecked)).not.toBeChecked();
    mocks.locale = 'es-ES';
    view.rerender(<ContractLifecycle contract={contract} onClose={vi.fn()} onChanged={vi.fn()} />);
    expect(screen.getByLabelText(es.contractLifecycle.reason)).toHaveValue('Unsaved local reason');
    expect(screen.getByRole('button', { name: es.contractLifecycle.confirm })).toBeDisabled();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('requires fresh review consent when selecting a different draft with the same revision and hash', async () => {
    const first = reviewed(); const second = reviewed({ id: 'draft-2', data: { ...renewalData, reason: 'Second reason' } });
    mocks.drafts = [first, second]; mount(); await ready();
    const cards = screen.getAllByRole('button', { name: new RegExp(de.contractLifecycle.renewal) });
    fireEvent.click(cards[0]); fireEvent.click(screen.getByLabelText(de.contractLifecycle.confirmChecked));
    expect(screen.getByLabelText(de.contractLifecycle.confirmChecked)).toBeChecked();
    fireEvent.click(cards[1]);
    expect(screen.getByLabelText(de.contractLifecycle.confirmChecked)).not.toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: de.contractLifecycle.confirm }));
    expect(screen.getByRole('alert')).toHaveTextContent(de.contractLifecycle.confirmRequired);
    expect(mocks.confirm).not.toHaveBeenCalled();
  });

  it('preserves typed changes on conflict reload and requires saving/reviewing before another confirmation', async () => {
    const item = reviewed(); mocks.drafts = [item]; mocks.byId.set(item.id, item);
    mount(); await ready(); fireEvent.click(screen.getByRole('button', { name: new RegExp(de.contractLifecycle.renewal) }));
    fireEvent.change(screen.getByLabelText(de.contractLifecycle.reason), { target: { value: 'Keep this local correction' } });
    mocks.post.mockRejectedValueOnce(Object.assign(new Error('Changed remotely'), { statusCode: 412 }));
    fireEvent.click(screen.getByRole('button', { name: de.contractLifecycle.saveChanges }));
    await screen.findByRole('alert'); mocks.sourceEtag = '"new-source"';
    fireEvent.click(screen.getByRole('button', { name: de.contractLifecycle.reloadReview }));
    await waitFor(() => expect(screen.queryByText(de.contractLifecycle.loading)).not.toBeInTheDocument());
    expect(screen.getByLabelText(de.contractLifecycle.reason)).toHaveValue('Keep this local correction');
    expect(screen.getByLabelText(de.contractLifecycle.confirmChecked)).not.toBeChecked();
    expect(screen.getByRole('button', { name: de.contractLifecycle.confirm })).toBeDisabled();
  });

  it.each([500, 502, 503])('freezes other commands after HTTP %s and retries the exact confirmed revision/hash', async statusCode => {
    const item = reviewed(); mocks.drafts = [item]; mocks.byId.set(item.id, item);
    mount(); await ready(); fireEvent.click(screen.getByRole('button', { name: new RegExp(de.contractLifecycle.renewal) }));
    fireEvent.click(screen.getByLabelText(de.contractLifecycle.confirmChecked));
    mocks.post.mockRejectedValueOnce(Object.assign(new Error('Unclear delivery'), { statusCode }));
    fireEvent.click(screen.getByRole('button', { name: de.contractLifecycle.confirm }));
    await screen.findByRole('alert'); const original = mocks.post.mock.calls[0];
    expect(screen.getByRole('button', { name: de.contractLifecycle.saveChanges })).toBeDisabled();
    expect(screen.getByRole('button', { name: de.contractLifecycle.review })).toBeDisabled();
    expect(screen.getByLabelText(de.contractLifecycle.reason)).toBeDisabled();
    mocks.sourceEtag = '"newer-source"';
    fireEvent.click(screen.getByRole('button', { name: de.contractLifecycle.retryExact }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    expect(mocks.post.mock.calls[1][0]).toBe(original[0]);
    expect(mocks.post.mock.calls[1][1]).toBe(original[1]);
    expect(mocks.post.mock.calls[1][1]).toMatchObject({ expected_revision: item.revision,
      reviewed_hash: item.review_hash, expected_contract_etag: '"immo-contract-etag-1"', confirmed: true });
    expect(mocks.confirm).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.getByText(de.contractLifecycle.state_confirmed, { selector: '[role="status"]' })).toBeInTheDocument());
  });

  it('shows the current superseded state after replaying an old immutable pending confirmation', async () => {
    const item = reviewed({ data: terminationData }); mocks.drafts = [item]; mocks.byId.set(item.id, item);
    mount(); await ready(); fireEvent.click(screen.getByRole('button', { name: new RegExp(de.contractLifecycle.termination) }));
    fireEvent.click(screen.getByLabelText(de.contractLifecycle.confirmChecked));
    mocks.post.mockRejectedValueOnce(Object.assign(new Error('Lost response'), { statusCode: 502 }));
    fireEvent.click(screen.getByRole('button', { name: de.contractLifecycle.confirm })); await screen.findByRole('alert');
    const frozen = reviewed({ data: terminationData, state: 'pending_effective' });
    mocks.drafts = []; mocks.history = [historyItem(frozen, { current_state: 'superseded', superseded_by_draft_id: 'newer-draft' })];
    mocks.byId.set(frozen.id, { ...frozen, state: 'superseded', superseded_by_draft_id: 'newer-draft' });
    mocks.post.mockResolvedValueOnce(frozen);
    fireEvent.click(screen.getByRole('button', { name: de.contractLifecycle.retryExact }));
    expect(await screen.findByText(de.contractLifecycle.supersededNoFinalize)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: de.contractLifecycle.finalize })).not.toBeInTheDocument();
    expect(mocks.history[0].result.state).toBe('pending_effective');
    expect(mocks.history[0].result.superseded_by_draft_id).toBeNull();
  });

  it.each(['property_id', 'unit_id', 'tenant_id', 'data'])('refuses inconsistent review %s before showing its private content', async field => {
    const item = reviewed();
    if (field === 'data') item.review.data = { ...item.data, reason: 'Unrelated reviewed PII' };
    else item.review.source_contract[field] = 'foreign-subject';
    mocks.drafts = [item]; mount(); await ready();
    expect(screen.getByRole('alert')).toHaveTextContent(de.contractLifecycle.malformed);
    expect(screen.queryByText(item.data.reason)).not.toBeInTheDocument();
    expect(screen.queryByText('Unrelated reviewed PII')).not.toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('accepts a completed-at-confirmation result with no later finalization ETag', async () => {
    mocks.canWrite = false;
    const complete = reviewed({ state: 'completed', data: terminationData, finalized_contract_etag: null });
    mocks.history = [historyItem(complete)]; mount(); await ready();
    fireEvent.click(screen.getByRole('button', { name: new RegExp(de.contractLifecycle.termination) }));
    expect(screen.getByRole('status')).toHaveTextContent(de.contractLifecycle.state_completed);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('rejects a successful command bound to another draft on the same contract', async () => {
    const item = reviewed(); mocks.drafts = [item]; mocks.byId.set(item.id, item);
    const changed = vi.fn(); mount({ onChanged: changed }); await ready();
    fireEvent.click(screen.getByRole('button', { name: new RegExp(de.contractLifecycle.renewal) }));
    fireEvent.click(screen.getByLabelText(de.contractLifecycle.confirmChecked));
    mocks.post.mockResolvedValueOnce(reviewed({ id: 'other-draft', state: 'confirmed' }));
    fireEvent.click(screen.getByRole('button', { name: de.contractLifecycle.confirm }));
    expect(await screen.findByRole('alert')).toHaveTextContent(de.contractLifecycle.malformed);
    expect(changed).not.toHaveBeenCalled();
  });

  it('suppresses duplicate submission and every close path while preparing/sending', async () => {
    const response = pending(); const close = vi.fn(); mount({ onClose: close }); await ready(); await fillRenewal();
    mocks.post.mockReturnValueOnce(response.promise);
    const save = screen.getByRole('button', { name: de.contractLifecycle.saveDraft });
    fireEvent.click(save); fireEvent.click(save);
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-busy', 'true');
    screen.getAllByRole('button', { name: de.contractLifecycle.close }).forEach(button => fireEvent.click(button));
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    fireEvent.mouseDown(screen.getByRole('dialog').parentElement);
    expect(close).not.toHaveBeenCalled();
    await act(async () => response.resolve(draft({ data: mocks.post.mock.calls[0][1].data })));
    await waitFor(() => expect(screen.getByRole('dialog')).toHaveAttribute('aria-busy', 'false'));
  });

  it('aborts pending private reads when the actor changes and ignores late old-actor data', async () => {
    const response = pending(); let oldSignal;
    const baseGet = mocks.get.getMockImplementation();
    mocks.get.mockImplementation((path, options) => {
      if (path.endsWith('/drafts?limit=25') && mocks.auth.id === 'actor-1') { oldSignal = options.signal; return response.promise; }
      return baseGet(path, options);
    });
    const view = mount(); await waitFor(() => expect(oldSignal).toBeDefined());
    mocks.auth = { ...mocks.auth, id: 'actor-2' };
    view.rerender(<ContractLifecycle contract={contract} onClose={vi.fn()} onChanged={vi.fn()} />);
    await ready(); expect(oldSignal.aborted).toBe(true);
    await act(async () => response.resolve(page([draft({ data: { ...renewalData, reason: 'Old actor private draft' } })])));
    expect(screen.queryByText('Old actor private draft')).not.toBeInTheDocument();
  });

  it('clears cached private review data when fresh source access is revoked on the server', async () => {
    const item = reviewed(); mocks.drafts = [item]; mocks.byId.set(item.id, item);
    mount(); await ready(); fireEvent.click(screen.getByRole('button', { name: new RegExp(de.contractLifecycle.renewal) }));
    const baseGet = mocks.get.getMockImplementation();
    mocks.get.mockImplementation((path, options) => path === '/contracts/contract-1'
      ? Promise.reject(Object.assign(new Error('Access revoked'), { statusCode: 403 })) : baseGet(path, options));
    fireEvent.click(screen.getByRole('button', { name: de.contractLifecycle.review }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Access revoked');
    expect(screen.queryByText(renewalData.reason)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(de.contractLifecycle.reason)).not.toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('loads after StrictMode effect cleanup without reviving the aborted first load', async () => {
    render(<StrictMode><ContractLifecycle contract={contract} onClose={vi.fn()} /></StrictMode>);
    await ready(); expect(screen.getByRole('button', { name: de.contractLifecycle.saveDraft })).toBeEnabled();
    expect(mocks.get.mock.calls.some(([, options]) => options.signal.aborted)).toBe(true);
  });

  it('wraps keyboard focus and restores the opener on close at narrow-dialog semantics', async () => {
    function Harness() {
      const [open, setOpen] = useState(false); const [opener, setOpener] = useState(null);
      return <><button onClick={event => { setOpener(event.currentTarget); setOpen(true); }}>Open workflow</button>
        {open && <ContractLifecycle contract={contract} opener={opener} onClose={() => setOpen(false)} />}</>;
    }
    render(<Harness />);
    const opener = screen.getByRole('button', { name: 'Open workflow' });
    opener.focus(); fireEvent.click(opener); await ready();
    const user = userEvent.setup();
    const closeButtons = screen.getAllByRole('button', { name: de.contractLifecycle.close });
    closeButtons.at(-1).focus();
    await user.tab();
    expect(closeButtons[0]).toHaveFocus();
    const sentinels = screen.getByRole('dialog').querySelectorAll('.contract-lifecycle__focus-sentinel');
    sentinels[0].focus();
    expect(closeButtons.at(-1)).toHaveFocus();
    await user.click(closeButtons.at(-1));
    expect(opener).toHaveFocus();
  });

  it('restores focus to the refreshed row action after successful commands replace the original opener', async () => {
    function Harness() {
      const [open, setOpen] = useState(false); const [opener, setOpener] = useState(null);
      const [refreshed, setRefreshed] = useState(false);
      return <><button key={String(refreshed)} data-lifecycle-contract={contract.id}
        onClick={event => { setOpener(event.currentTarget); setOpen(true); }}>Open workflow</button>
        {open && <ContractLifecycle contract={contract} opener={opener} onClose={() => setOpen(false)}
          onChanged={() => setRefreshed(true)} />}</>;
    }
    render(<Harness />); const original = screen.getByRole('button', { name: 'Open workflow' });
    fireEvent.click(original); await ready(); await fillRenewal();
    fireEvent.click(screen.getByRole('button', { name: de.contractLifecycle.saveDraft }));
    await waitFor(() => expect(original.isConnected).toBe(false));
    await waitFor(() => expect(screen.getByRole('dialog')).toHaveAttribute('aria-busy', 'false'));
    fireEvent.click(screen.getAllByRole('button', { name: de.contractLifecycle.close }).at(-1));
    expect(screen.getByRole('button', { name: 'Open workflow' })).toHaveFocus();
  });

  it.each(['de-DE', 'en-US', 'es-ES'])('ships the complete lifecycle translation namespace in %s', locale => {
    const keys = Object.keys(languages['de-DE'].contractLifecycle).sort();
    expect(Object.keys(languages[locale].contractLifecycle).sort()).toEqual(keys);
    expect(keys.length).toBeGreaterThan(60);
  });
});
