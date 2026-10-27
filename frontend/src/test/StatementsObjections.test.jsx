import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, render, screen, fireEvent, within, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Statements from '../pages/Statements';
import { api } from '../api';

const state = vi.hoisted(() => ({ auth: null }));
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => state.auth,
  useCanWrite: () => state.auth?.write === null,
}));
vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), put: vi.fn(), upload: vi.fn(),
  getBlob: vi.fn(), captureSession: vi.fn(() => () => {}) } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key, locale: 'de-DE' }) }));

const original = { id: 'bp', property_id: 'p', label: 'Original BK 2025', start_date: '2025-01-01', end_date: '2025-12-31', status: 'disputed' };
const objection = { id: 'o1', billing_period_id: 'bp', statement_id: 's1', received_on: '2026-10-18',
  reason: 'Fläche der Wohnung wird bestritten', status: 'open', decision_revision: 0 };
const source = 'a'.repeat(64);
let data;

function page() { return <MemoryRouter><Statements /></MemoryRouter>; }
async function openPeriod(label = original.label) {
  const row = (await screen.findByRole('cell', { name: label === original.label ? 'Prüfhaus' : 'Zweites Prüfhaus' })).closest('tr');
  fireEvent.click(within(row).getByRole('button', { name: 'Kosten und Abrechnung öffnen' }));
  await screen.findByRole('heading', { name: label });
}
async function openDecision(action = 'reject') {
  fireEvent.click(await screen.findByRole('button', { name: action === 'reject'
    ? `Widerspruch zurückweisen: ${objection.reason}` : `Abrechnung überarbeiten: ${objection.reason}` }));
  return screen.findByRole('dialog', { name: action === 'reject'
    ? 'Widerspruch begründet zurückweisen' : 'Abrechnung begründet überarbeiten' });
}
function decide(reason = 'Der belegte Verteilungsschlüssel wurde fachlich geprüft') {
  fireEvent.change(screen.getByLabelText('Sachliche Begründung (mindestens 12 Zeichen)'), { target: { value: reason } });
}
function success(payload, action = 'reject') {
  const result = { ...objection, status: action === 'reject' ? 'rejected' : 'correction', decision_revision: 1,
    decision_reason: payload.rationale, decision_actor_id: 'owner', decided_at: '2026-10-18T12:00:00Z',
    correction_period_id: action === 'revise' ? 'correction' : null };
  data['/billing/objections?billing_period_id=bp'] = [result];
  data['/billing/periods/bp'] = { ...original, status: action === 'reject' ? 'delivered' : 'disputed' };
  return result;
}

beforeEach(() => {
  vi.clearAllMocks();
  state.auth = { user: { id: 'owner', role: 'eigentuemer' }, write: null };
  data = {
    '/billing/periods': [original], '/properties': [{ id: 'p', name: 'Prüfhaus' }],
    '/units': [{ id: 'u', label: 'WE Test' }], '/contracts': [{ id: 'c', tenant_id: 't' }],
    '/tenants': [{ id: 't', full_name: 'Synthetischer Mieter' }],
    '/billing/statements': [{ id: 's1', billing_period_id: 'bp', unit_id: 'u', contract_id: 'c',
      party: 'tenant', total_cost: 500, advance_paid: 400, balance: 100, status: 'finalized' }],
    '/billing/objections?billing_period_id=bp': [objection],
    '/billing/objections/o1/decision-preview': { objection, source_sha256: source, period_status: 'disputed' },
    '/billing/periods/bp': original,
    '/billing/periods/correction': { ...original, id: 'correction', label: 'Korrektur zur Prüfung', status: 'draft', corrects_period_id: 'bp', revision: 2 },
  };
  api.captureSession.mockReturnValue(() => {});
  api.get.mockImplementation(path => Promise.resolve(path.endsWith('/preflight')
    ? { has_blockers: false, blockers: [], warnings: [], metrics: {} } : data[path] ?? []));
  api.list.mockImplementation(path => Promise.resolve(data[path] ?? []));
  api.post.mockImplementation((path, payload) => Promise.resolve(success(payload, path.endsWith('/revise') ? 'revise' : 'reject')));
});

describe('Statements objection decisions', () => {
  it('opens a read-only period with Enter without exposing write actions', async () => {
    state.auth = { user: { id: 'reader', role: 'readonly' }, write: [] };
    render(page());
    const row = (await screen.findByRole('cell', { name: 'Prüfhaus' })).closest('tr');
    expect(within(row).queryByLabelText('ui.buttons.edit')).not.toBeInTheDocument();
    expect(row).toHaveAttribute('tabindex', '0');
    fireEvent.keyDown(row, { key: 'Enter' });
    await screen.findByRole('heading', { name: original.label });
    expect(screen.queryByRole('button', { name: /Widerspruch zurückweisen:/ })).not.toBeInTheDocument();
    expect(screen.queryByText('pages.statements.dispute')).not.toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });
  it('records the selected statement and received date with a nonempty original reason', async () => {
    data['/billing/periods'] = [{ ...original, status: 'finalized' }];
    data['/billing/objections?billing_period_id=bp'] = [];
    render(page()); await openPeriod();
    fireEvent.click(screen.getByText('pages.statements.dispute'));
    const dialog = screen.getByRole('dialog', { name: 'Widerspruch erfassen' });
    expect(within(dialog).getByText('Widerspruch speichern')).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText('Betroffene Abrechnung'), { target: { value: 's1' } });
    fireEvent.change(within(dialog).getByLabelText('Eingangsdatum'), { target: { value: '2026-10-17' } });
    fireEvent.change(within(dialog).getByLabelText('Begründung des Widerspruchs'), { target: { value: ' Fläche im Beleg falsch ' } });
    await act(async () => { fireEvent.click(within(dialog).getByText('Widerspruch speichern')); });
    expect(api.post).toHaveBeenCalledWith('/billing/periods/bp/objections', {
      statement_id: 's1', received_on: '2026-10-17', reason: 'Fläche im Beleg falsch',
      idempotency_key: expect.any(String),
    });
  });

  it('retains the creation command and dialog input after a lost answer', async () => {
    api.post.mockRejectedValueOnce(new TypeError('Erfassungsantwort verloren'));
    render(page()); await openPeriod();
    fireEvent.click(screen.getByText('pages.statements.dispute'));
    fireEvent.change(screen.getByLabelText('Begründung des Widerspruchs'), { target: { value: 'Fläche laut Beleg abweichend' } });
    await act(async () => { fireEvent.click(screen.getByText('Widerspruch speichern')); });
    expect(screen.getByText('Erfassungsantwort verloren')).toBeInTheDocument();
    expect(screen.getByLabelText('Begründung des Widerspruchs')).toHaveValue('Fläche laut Beleg abweichend');
    const first = api.post.mock.calls[0];
    expect(first[1].idempotency_key).toEqual(expect.any(String));
    await act(async () => { fireEvent.click(screen.getByText('Widerspruch speichern')); });
    expect(api.post.mock.calls[1]).toEqual(first);
  });

  it('keeps the creation key when inputs change after an uncertain answer instead of silently creating a new command', async () => {
    api.post.mockRejectedValueOnce(new TypeError('Erfassungsantwort verloren'))
      .mockRejectedValueOnce(Object.assign(new Error('Vorgangskennung mit anderen Angaben'), { statusCode: 409 }));
    render(page()); await openPeriod();
    fireEvent.click(screen.getByText('pages.statements.dispute'));
    fireEvent.change(screen.getByLabelText('Begründung des Widerspruchs'), { target: { value: 'Ursprünglicher Einwand' } });
    await act(async () => { fireEvent.click(screen.getByText('Widerspruch speichern')); });
    fireEvent.change(screen.getByLabelText('Begründung des Widerspruchs'), { target: { value: 'Geänderter Einwand' } });
    await act(async () => { fireEvent.click(screen.getByText('Widerspruch speichern')); });
    expect(api.post.mock.calls[1][1].idempotency_key).toEqual(api.post.mock.calls[0][1].idempotency_key);
    expect(api.post.mock.calls[1][1].reason).toBe('Geänderter Einwand');
    expect(screen.getByRole('dialog', { name: 'Widerspruch erfassen' })).toBeInTheDocument();
    expect(screen.getByText('Vorgangskennung mit anderen Angaben')).toBeInTheDocument();
  });

  it('uses the current period state after an old creation command is replayed', async () => {
    api.post.mockResolvedValue({ ...objection, status: 'resolved' });
    data['/billing/periods/bp'] = { ...original, status: 'corrected' };
    render(page()); await openPeriod();
    fireEvent.click(screen.getByText('pages.statements.dispute'));
    fireEvent.change(screen.getByLabelText('Begründung des Widerspruchs'), { target: { value: 'Bereits erfasster Einwand' } });
    await act(async () => { fireEvent.click(screen.getByText('Widerspruch speichern')); });
    expect(screen.getAllByText('Korrigiert').length).toBeGreaterThan(0);
    expect(screen.queryByText('pages.statements.dispute')).not.toBeInTheDocument();
    expect(api.post).toHaveBeenCalledTimes(1);
  });

  it('shows original reason and records the hash-bound rejection, author and timestamp', async () => {
    render(page()); await openPeriod(); await openDecision();
    expect(screen.getAllByText(objection.reason).length).toBeGreaterThan(1);
    expect(screen.getByText('Ablehnung mit Begründung bestätigen')).toBeDisabled();
    decide();
    await act(async () => { fireEvent.click(screen.getByText('Ablehnung mit Begründung bestätigen')); });
    expect(api.post).toHaveBeenCalledWith('/billing/objections/o1/reject', {
      expected_revision: 0, expected_source_sha256: source,
      idempotency_key: expect.any(String), rationale: 'Der belegte Verteilungsschlüssel wurde fachlich geprüft',
    });
    expect(screen.getByText('Begründet zurückgewiesen')).toBeInTheDocument();
    expect(screen.getByText(/Autor: owner/)).toBeInTheDocument();
    expect(screen.getByText(objection.reason)).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('keeps the rationale and identical idempotency key after a lost response', async () => {
    api.post.mockRejectedValueOnce(new TypeError('Antwort verloren'));
    render(page()); await openPeriod(); await openDecision(); decide();
    await act(async () => { fireEvent.click(screen.getByText('Ablehnung mit Begründung bestätigen')); });
    expect(screen.getByText('Antwort verloren')).toBeInTheDocument();
    expect(screen.getByLabelText('Sachliche Begründung (mindestens 12 Zeichen)')).toHaveValue('Der belegte Verteilungsschlüssel wurde fachlich geprüft');
    await act(async () => { fireEvent.click(screen.getByText('Ablehnung mit Begründung bestätigen')); });
    expect(api.post.mock.calls[0]).toEqual(api.post.mock.calls[1]);
  });

  it('opens a separate correction draft through the documented revise command', async () => {
    render(page()); await openPeriod(); await openDecision('revise'); decide('Die abweichende Fläche wird in einer Korrektur neu berechnet');
    await act(async () => { fireEvent.click(screen.getByText('Überarbeitung mit Begründung starten')); });
    expect(api.post).toHaveBeenCalledWith('/billing/objections/o1/revise', expect.objectContaining({ expected_source_sha256: source }));
    expect(await screen.findByRole('heading', { name: 'Korrektur zur Prüfung' })).toBeInTheDocument();
    expect(api.post.mock.calls).toHaveLength(1);
  });

  it('refuses a stale preview without submitting a decision', async () => {
    data['/billing/objections/o1/decision-preview'].objection = { ...objection, status: 'correction' };
    render(page()); await openPeriod();
    await act(async () => { fireEvent.click(await screen.findByRole('button', { name: `Widerspruch zurückweisen: ${objection.reason}` })); });
    expect(screen.getByText('Widerspruch wurde geändert. Bitte die Liste erneut laden.')).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('closes the stale decision and reloads after the server reports a revision conflict', async () => {
    api.post.mockRejectedValueOnce(Object.assign(new Error('Neuere Entscheidung vorhanden'), { statusCode: 409 }));
    render(page()); await openPeriod(); await openDecision(); decide();
    await act(async () => { fireEvent.click(screen.getByText('Ablehnung mit Begründung bestätigen')); });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(api.post).toHaveBeenCalledTimes(1);
    expect(api.get.mock.calls.filter(([path]) => path.includes('objections?'))).toHaveLength(2);
  });

  it('removes an open decision when the current role or write permission is withdrawn', async () => {
    const result = render(page()); await openPeriod(); await openDecision(); decide();
    state.auth = { user: { id: 'owner', role: 'readonly' }, write: [] };
    result.rerender(page());
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /Widerspruch zurückweisen:/ })).not.toBeInTheDocument();
    expect(screen.queryByText('pages.statements.dispute')).not.toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('ignores an old period objection response after navigation', async () => {
    let resolveOld;
    const other = { ...original, id: 'other', property_id: 'p2', label: 'Anderer Zeitraum' };
    data['/billing/periods'] = [original, other];
    data['/properties'].push({ id: 'p2', name: 'Zweites Prüfhaus' });
    const normal = api.get.getMockImplementation();
    api.get.mockImplementation(path => path === '/billing/objections?billing_period_id=bp'
      ? new Promise(resolve => { resolveOld = resolve; }) : normal(path));
    render(page()); await openPeriod();
    fireEvent.click(screen.getByRole('button', { name: /pages.statements.back/ }));
    await openPeriod(other.label);
    await act(async () => { resolveOld([objection]); });
    expect(screen.queryByText(objection.reason)).not.toBeInTheDocument();
  });
});
