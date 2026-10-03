import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import BillingDisputeWorkspace from '../features/billingDisputes/BillingDisputeWorkspace';
import DisputeCommandPanel from '../features/billingDisputes/DisputeCommandPanel';
import { appendCommand, openCommand, readPreview } from '../features/billingDisputes/disputeModel';
import { caseRow, event, evidence, originalStatement, periodStatus, preview } from './fixtures/disputes';

const mocks = vi.hoisted(() => ({ user: { id: 'actor', role: 'eigentuemer', portfolio_access: 'all' }, get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), stored: null }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: mocks.user, role: mocks.user.role }) }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: 'de-DE', t: key => key }) }));
const copy = value => structuredClone(value);
const stamp = { revision: '00000000-0000-4000-8000-000000000001', updated_at: '2026-10-03T12:00:00Z', expires_at: '2026-10-10T12:00:00Z' };
const choice = row => ({ id: row.id, label: `Original ${row.revision}`, billing_period_id: row.billing_period_id, contract_id: row.contract_id, unit_id: row.unit_id, revision: row.revision, snapshot_hash: row.snapshot_hash, status: row.status });
const choices = (items, selected = null, cursor = null) => ({ items, selected, has_more: Boolean(cursor), next_cursor: cursor });
const pending = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
function read(path) {
  if (path.startsWith('/auth/users/me/form-drafts')) return Promise.resolve({ draft: copy(mocks.stored) });
  if (path.endsWith('/periods/period/status')) return Promise.resolve(copy(periodStatus));
  if (path.startsWith('/billing/disputes?')) return Promise.resolve({ items: [], next_after_id: null });
  if (path === '/billing/disputes/case') return Promise.resolve(copy(caseRow));
  if (path === '/billing/statements/statement-original') return Promise.resolve(copy(originalStatement));
  if (path.startsWith('/workflow-references/documents')) return Promise.resolve(choices([{ id: 'document', label: 'Synthetisches Dokument' }]));
  if (path.startsWith('/workflow-references/statements')) {
    const query = new URLSearchParams(path.split('?')[1]);
    return Promise.resolve(choices([choice(originalStatement)], query.get('selected_id') === originalStatement.id ? choice(originalStatement) : null));
  }
  if (path.startsWith('/documents/document/versions')) {
    const before = new URLSearchParams(path.split('?')[1]).get('before');
    return Promise.resolve({ document_id: 'document', items: Array.from({ length: before ? 2 : 25 }, (_, index) => {
      const number = (before ? 2 : 27) - index;
      return { ...evidence, id: `version-${number}`, number, filename: `Original-${number}.txt`, created_at: '2026-10-01T12:00:00Z' };
    }), next_before: before ? null : 3 });
  }
  throw new Error(`Unexpected actual path ${path}`);
}
function workspace() { return render(<BillingDisputeWorkspace periodId="period" propertyId="property" />); }
function panel(command, caseId = '') { return render(<DisputeCommandPanel periodId="period" propertyId="property" principal="actor" initialCommand={command} caseId={caseId} />); }
async function newFile() {
  const view = workspace(); fireEvent.click(await screen.findByRole('button', { name: 'Neue Akte erfassen' }));
  await screen.findByText('formDraft.status.ready');
  fireEvent.change(screen.getByLabelText('Grund / Notiz'), { target: { value: 'Mein tatsächlicher Grund' } });
  fireEvent.change(screen.getByLabelText('Tatsächlicher Eingang'), { target: { value: '2026-10-01' } });
  fireEvent.click(await screen.findByRole('button', { name: 'Original 3' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Geprüften Originalstand übernehmen' }));
  expect(screen.getByRole('heading', { name: 'Neue Akte erfassen' })).toHaveFocus();
  return view;
}
beforeEach(() => {
  vi.clearAllMocks(); mocks.stored = null; mocks.user = { id: 'actor', role: 'eigentuemer', portfolio_access: 'all' };
  mocks.get.mockImplementation(read); mocks.put.mockImplementation((_path, data) => { mocks.stored = { ...copy(data), ...stamp }; return Promise.resolve(stamp); });
  mocks.del.mockResolvedValue({ discarded: true });
  mocks.post.mockImplementation((path, command) => path.endsWith('/preview') ? Promise.resolve({ ...preview(command),
    binding: path.includes('/case/') ? copy(caseRow) : preview(command).binding,
    evidence: command.evidence_version_ids.map(id => ({ ...evidence, version_id: id, filename: 'Geprüftes Original.txt' })) })
    : Promise.resolve({ case_id: 'case', event_id: 'event', revision: command.expected_revision ? command.expected_revision + 1 : 1 }));
});

describe('dispute command forms, originals and protected choices', () => {
  it('uses bounded document/version pages, literal original positions and unchanged preview confirmation', async () => {
    await newFile();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Position 1: Original position 1' }));
    const positions = screen.getByRole('navigation', { name: 'Beanstandete Originalpositionen' });
    fireEvent.click(within(positions).getByRole('button', { name: 'Nächste Seite' }));
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Position 28: Original position 28' }));
    fireEvent.click(screen.getByRole('button', { name: 'Synthetisches Dokument' }));
    await screen.findByRole('button', { name: 'Version 27 · Original-27.txt' });
    expect(screen.queryByRole('button', { name: 'Version 1 · Original-1.txt' })).not.toBeInTheDocument();
    fireEvent.click(within(screen.getByRole('navigation', { name: 'Archivierte Originalversion' })).getByRole('button', { name: 'Nächste Seite' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Version 1 · Original-1.txt' }));
    fireEvent.click(screen.getByRole('button', { name: 'Vorschau prüfen' }));
    const review = await screen.findByRole('region', { name: 'Geprüfte Vorschau' });
    expect(within(review).getByText('Geprüftes Original.txt')).toBeInTheDocument();
    expect(mocks.post.mock.calls[0][1]).toMatchObject({ line_item_refs: [0, 27], evidence_version_ids: ['version-1'], expected_statement_revision: 3 });
    fireEvent.click(within(review).getByRole('button', { name: 'Unverändert bestätigen' }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    const prepared = mocks.put.mock.calls.find(([, row]) => row.submission_pending)[1];
    expect(mocks.post.mock.calls[1][1]).toEqual(JSON.parse(prepared.values.command_json));
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Widerspruchsakten' })).toHaveFocus());
    expect(mocks.get.mock.calls.some(([path]) => path === '/documents/document/versions?limit=25&before=3')).toBe(true);
    expect(mocks.get.mock.calls.some(([path]) => path.startsWith('/workflow-references/statements?period_id=period'))).toBe(true);
  });
  it('locks the prepared preview after a lost response and exposes only the exact retry', async () => {
    await newFile(); fireEvent.click(screen.getByRole('button', { name: 'Vorschau prüfen' }));
    await screen.findByRole('region', { name: 'Geprüfte Vorschau' }); mocks.post.mockRejectedValueOnce(new Error('Antwort verloren'));
    fireEvent.click(screen.getByRole('button', { name: 'Unverändert bestätigen' }));
    const retry = await screen.findByRole('button', { name: 'Denselben Befehl erneut senden' });
    expect(screen.queryByRole('button', { name: 'Eingaben bearbeiten' })).not.toBeInTheDocument(); expect(screen.queryByLabelText('Grund / Notiz')).not.toBeInTheDocument();
    const first = copy(mocks.post.mock.calls[1][1]); fireEvent.click(retry);
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(3)); expect(mocks.post.mock.calls[2][1]).toEqual(first);
  });
  it('preserves known conflict inputs until the user explicitly adopts the newly loaded case revision', async () => {
    const command = { ...appendCommand(caseRow, 'note', 'event-key'), reason: 'Erhaltene Notiz', observed_on: '2026-10-01' }; panel(command, 'case');
    await screen.findByText('formDraft.status.ready'); await screen.findByText('Original position 1');
    mocks.post.mockRejectedValueOnce(Object.assign(new Error('Stand geändert'), { statusCode: 412 })); fireEvent.click(screen.getByRole('button', { name: 'Vorschau prüfen' }));
    await screen.findByText('Stand geändert'); expect(screen.getByLabelText('Grund / Notiz')).toHaveValue('Erhaltene Notiz');
    mocks.get.mockImplementation(path => path === '/billing/disputes/case' ? Promise.resolve({ ...caseRow, revision: 28, latest_event: { ...caseRow.latest_event, revision: 28 } }) : read(path));
    fireEvent.click(await screen.findByRole('button', { name: 'Aktuellen Stand laden' }));
    const adopt = await screen.findByRole('button', { name: 'Geprüften Originalstand übernehmen' }); expect(screen.getByRole('button', { name: 'Vorschau prüfen' })).toBeDisabled();
    mocks.post.mockImplementation((_path, command) => Promise.resolve({ ...preview(command), binding: { ...caseRow, revision: 28 } }));
    fireEvent.click(adopt); fireEvent.click(screen.getByRole('button', { name: 'Vorschau prüfen' }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2)); expect(mocks.post.mock.calls[1][1]).toMatchObject({ expected_revision: 28, idempotency_key: 'event-key', reason: 'Erhaltene Notiz' });
    await screen.findByRole('region', { name: 'Geprüfte Vorschau' });
  });
  it('accepts a genuine correction from its own later period through the case-bound selected metadata', async () => {
    const corrected = { ...originalStatement, id: 'correction', billing_period_id: 'correction-period', revision: 4, snapshot_hash: 'e'.repeat(64), source_statement_id: originalStatement.id };
    mocks.get.mockImplementation(path => path.startsWith('/workflow-references/statements') ? Promise.resolve(choices([choice(corrected)], path.includes('selected_id=correction') ? choice(corrected) : null))
      : path === '/billing/statements/correction' ? Promise.resolve(copy(corrected)) : read(path));
    mocks.post.mockImplementation((path, command) => Promise.resolve({ ...preview(command), binding: copy(caseRow), correction: { id: corrected.id, revision: 4, snapshot_hash: corrected.snapshot_hash } }));
    panel({ ...appendCommand(caseRow, 'correction_link', 'link-key'), reason: 'Korrektur geprüft', observed_on: '2026-10-01' }, 'case');
    await screen.findByText('formDraft.status.ready'); fireEvent.click(await screen.findByRole('button', { name: 'Original 4' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Vorschau prüfen' })).toBeEnabled()); fireEvent.click(screen.getByRole('button', { name: 'Vorschau prüfen' }));
    await screen.findByRole('region', { name: 'Geprüfte Vorschau' }); expect(mocks.post.mock.calls[0][1].correction_statement_id).toBe('correction');
    expect(mocks.get.mock.calls.some(([path]) => path.startsWith('/workflow-references/statements?dispute_case_id=case'))).toBe(true);
  });
  it('shows a missing property original as a real limitation and blocks preview', async () => {
    panel({ ...openCommand('period', { property_review_snapshot_hash: null }, 'property_review', 'owner-key'), reason: 'Objektprüfung', received_on: '2026-10-01' });
    await screen.findByText('Diese Periode liefert kein vollständiges unveränderbares Objektoriginal.');
    expect(screen.getByRole('button', { name: 'Vorschau prüfen' })).toBeDisabled(); expect(mocks.post).not.toHaveBeenCalled();
  });
  it('hides the whole command context on a denied reference read', async () => {
    mocks.get.mockImplementation(path => path.startsWith('/workflow-references/documents') ? Promise.reject(Object.assign(new Error('Forbidden'), { statusCode: 403 })) : read(path));
    workspace(); fireEvent.click(await screen.findByRole('button', { name: 'Neue Akte erfassen' }));
    await screen.findByText('Der Zugriff wurde geändert oder die Akte ist nicht verfügbar.');
    expect(screen.queryByLabelText('Grund / Notiz')).not.toBeInTheDocument(); expect(screen.queryByText('Beanstandete Originalfassung')).not.toBeInTheDocument();
  });
  it('hides a preserved preview on a denied encrypted draft write and sends no domain command', async () => {
    await newFile(); fireEvent.click(screen.getByRole('button', { name: 'Vorschau prüfen' }));
    await screen.findByRole('region', { name: 'Geprüfte Vorschau' });
    mocks.put.mockRejectedValueOnce(Object.assign(new Error('Access denied'), { statusCode: 403 }));
    fireEvent.click(screen.getByRole('button', { name: 'Unverändert bestätigen' }));
    await screen.findByText('Der Zugriff wurde geändert oder die Akte ist nicht verfügbar.');
    expect(screen.queryByRole('region', { name: 'Geprüfte Vorschau' })).not.toBeInTheDocument();
    expect(mocks.post).toHaveBeenCalledTimes(1);
  });
  it('aborts a delayed preview and hides original inputs immediately on actor change', async () => {
    const view = await newFile(); const delayed = pending(); mocks.post.mockReturnValueOnce(delayed.promise); fireEvent.click(screen.getByRole('button', { name: 'Vorschau prüfen' }));
    const signal = mocks.post.mock.calls[0][2].signal; mocks.user = { ...mocks.user, id: 'other-actor', role: 'readonly' };
    view.rerender(<BillingDisputeWorkspace periodId="period" propertyId="property" />);
    expect(signal.aborted).toBe(true); expect(screen.queryByLabelText('Grund / Notiz')).not.toBeInTheDocument();
    await act(async () => { delayed.resolve(preview(mocks.post.mock.calls[0][1])); });
    expect(screen.queryByRole('region', { name: 'Geprüfte Vorschau' })).not.toBeInTheDocument(); expect(screen.queryByRole('button', { name: 'Neue Akte erfassen' })).not.toBeInTheDocument();
  });
  it('restores a pending reviewed command as locked UI and retains it past the real autosave interval', async () => {
    const command = { ...openCommand('period', originalStatement, 'tenant_statement', 'original-pending-key'), reason: 'Originaler ausstehender Befehl', received_on: '2026-10-01' };
    const checked = readPreview(preview(command), command);
    const values = { period_id: 'period', case_id: '', command_json: JSON.stringify(checked.command), review_json: JSON.stringify(checked.review) };
    mocks.stored = { ...stamp, schema: JSON.stringify(['case_id', 'command_json', 'period_id', 'review_json'].map(key => [key, 'text'])), values, original_values: { ...values, review_json: '' }, edit_revision: null, submission_pending: true };
    workspace(); fireEvent.click(await screen.findByRole('button', { name: 'Neue Akte erfassen' }));
    fireEvent.click(await screen.findByRole('button', { name: 'formDraft.restoreAfterReview' }));
    await screen.findByRole('button', { name: 'Denselben Befehl erneut senden' });
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 850)); });
    expect(mocks.put).not.toHaveBeenCalled(); expect(mocks.post).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Eingaben bearbeiten' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'formDraft.discard' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Denselben Befehl erneut senden' }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1)); expect(mocks.post.mock.calls[0][1]).toEqual(checked.command);
  });
  it('opens a real original event before recording its correction and never overwrites the original', async () => {
    mocks.get.mockImplementation(path => path.startsWith('/billing/disputes?') ? Promise.resolve({ items: [caseRow], next_after_id: null })
      : path.includes('/case/journal?') ? Promise.resolve({ items: [event(1)], next_after: null, revision: 27 })
      : path === '/billing/disputes/case/events/event-1' ? Promise.resolve(event(1)) : read(path));
    workspace(); fireEvent.click(await screen.findByRole('button', { name: 'Akte · statement-original' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Originalereignis öffnen · Revision 1' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Originalereignis berichtigen' }));
    await screen.findByText('formDraft.status.ready');
    fireEvent.change(screen.getByLabelText('Grund / Notiz'), { target: { value: 'Eigenständige Berichtigung' } });
    fireEvent.change(screen.getByLabelText('Tatsächliches Beobachtungsdatum'), { target: { value: '2026-10-02' } });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Vorschau prüfen' })).toBeEnabled());
    expect(within(screen.getByRole('region', { name: 'Berichtigt Originalereignis' })).getByText('Original reason 1')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Vorschau prüfen' })); await screen.findByRole('region', { name: 'Geprüfte Vorschau' });
    expect(mocks.post.mock.calls[0][1]).toMatchObject({ corrects_event_id: 'event-1', expected_revision: 27, kind: 'correction', reason: 'Eigenständige Berichtigung', observed_on: '2026-10-02' });
    expect(mocks.post.mock.calls.every(([path]) => path === '/billing/disputes/case/preview')).toBe(true);
  });
  it('hides a pending context when the same actor loses the actual billing grant', async () => {
    const view = await newFile(); const delayed = pending(); mocks.post.mockReturnValueOnce(delayed.promise); fireEvent.click(screen.getByRole('button', { name: 'Vorschau prüfen' }));
    const signal = mocks.post.mock.calls[0][2].signal; mocks.user = { ...mocks.user, write_permissions: [] };
    view.rerender(<BillingDisputeWorkspace periodId="period" propertyId="property" />);
    expect(signal.aborted).toBe(true); expect(screen.queryByLabelText('Grund / Notiz')).not.toBeInTheDocument();
    await act(async () => { delayed.resolve(preview(mocks.post.mock.calls[0][1])); });
    expect(screen.queryByRole('region', { name: 'Geprüfte Vorschau' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Neue Akte erfassen' })).not.toBeInTheDocument();
  });
});
