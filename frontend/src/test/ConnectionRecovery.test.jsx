import { useState } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '../api';
import ConnectionEvidencePanel from '../pages/ConnectionEvidencePanel';
import ConnectionEmergencyStop from '../pages/ConnectionEmergencyStop';

const access = vi.hoisted(() => ({ write: true }));
vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), captureSession: vi.fn() } }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => access.write }));
const run = { id: 'run-a', connection_id: 'c-a', revision: 3, state: 'unknown', attempts: 1, recorded_attempts: 1, late_result_count: 1 };
const attempt = { id: 'attempt-a', run_id: run.id, number: 1, state: 'finished', detached: true, reviewed_at: null, result_bytes: 32 };
const proof = { attempt, manifest: { sha256: '1'.repeat(64), bytes: 32, blocks: 1 }, verified: true, projection: { success: true, token: '***' } };
const connection = { id: 'c-a', revision: 1, enabled: true, read_error: 'Geschützte Verbindungsdaten sind nicht lesbar.' };
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };

beforeEach(() => {
  vi.resetAllMocks(); access.write = true; api.captureSession.mockReturnValue(() => {});
  api.get.mockImplementation(url => {
    if (url.includes('/attempts?')) return Promise.resolve({ items: [attempt], total: 1, next_cursor: null });
    if (url.endsWith('/attempts/attempt-a')) return Promise.resolve(proof);
    if (url.endsWith('/runs/run-a')) return Promise.resolve({ ...run, revision: 7 });
    if (url.endsWith('/c-a/state')) return Promise.resolve({ ...connection, revision: 7 });
    throw new Error('Unexpected GET ' + url);
  });
});
afterEach(() => cleanup());

async function review(onApplied = vi.fn()) {
  render(<ConnectionEvidencePanel connectionId="c-a" run={run} onApplied={onApplied} />);
  fireEvent.click(await screen.findByRole('button', { name: /Versuch 1: Verspäteter Nachweis/ }));
  await screen.findByText('1'.repeat(64));
  fireEvent.change(screen.getByLabelText('Begründung des Abgleichs'), { target: { value: 'Nachweis beim Anbieter geprüft.' } });
  fireEvent.click(screen.getByLabelText(/Ich habe diesen gespeicherten Ergebnisnachweis geprüft/));
  return onApplied;
}

it('applies an explicitly reviewed stored result without any dispatch request', async () => {
  api.post.mockResolvedValue({ ...run, state: 'accepted', revision: 4 });
  const applied = await review();
  fireEvent.click(screen.getByRole('button', { name: 'Gespeicherten Nachweis übernehmen' }));
  await waitFor(() => expect(applied).toHaveBeenCalledWith(expect.objectContaining({ state: 'accepted' })));
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(api.post.mock.calls[0][0]).toBe('/integration-connections/c-a/runs/run-a/reconcile-recorded');
  expect(api.post.mock.calls[0][1]).toMatchObject({ base_revision: 3, attempt_id: 'attempt-a', confirm: true });
});

it('retries only the original reconciliation command after a lost acknowledgement', async () => {
  api.post.mockRejectedValueOnce(new Error('Antwort fehlt.')).mockResolvedValueOnce({ ...run, revision: 4, state: 'accepted' });
  await review(); fireEvent.click(screen.getByRole('button', { name: 'Gespeicherten Nachweis übernehmen' }));
  await screen.findByText('Antwort fehlt.');
  expect(screen.getByLabelText('Begründung des Abgleichs')).toBeDisabled();
  const original = api.post.mock.calls[0];
  fireEvent.click(screen.getByRole('button', { name: 'Abgleichsbestätigung erneut prüfen' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2));
  expect(api.post.mock.calls[1]).toEqual(original);
});

it('rejects a superficially verified response with no manifest before rendering or offering reconciliation', async () => {
  api.get.mockImplementation(url => url.includes('/attempts?') ? Promise.resolve({ items: [attempt], total: 1, next_cursor: null })
    : Promise.resolve({ attempt, verified: true, projection: {} }));
  render(<ConnectionEvidencePanel connectionId="c-a" run={run} onApplied={vi.fn()} />);
  fireEvent.click(await screen.findByRole('button', { name: /Versuch 1: Verspäteter Nachweis/ }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Der Ergebnisnachweis wurde nicht vollständig geprüft.');
  expect(screen.queryByRole('button', { name: 'Gespeicherten Nachweis übernehmen' })).not.toBeInTheDocument();
  expect(api.post).not.toHaveBeenCalled();
});

it('does not apply a verified proof belonging to another run', async () => {
  api.get.mockImplementation(url => url.includes('/attempts?') ? Promise.resolve({ items: [attempt], total: 1, next_cursor: null })
    : Promise.resolve({ ...proof, attempt: { ...attempt, run_id: 'other-run' } }));
  render(<ConnectionEvidencePanel connectionId="c-a" run={run} onApplied={vi.fn()} />);
  fireEvent.click(await screen.findByRole('button', { name: /Versuch 1: Verspäteter Nachweis/ }));
  await screen.findByRole('alert');
  expect(screen.queryByLabelText('Begründung des Abgleichs')).not.toBeInTheDocument();
  expect(api.post).not.toHaveBeenCalled();
});

it('provides a read-only refresh of the run after a reconciliation revision conflict', async () => {
  api.post.mockRejectedValue(Object.assign(new Error('Bitte den neuesten Stand prüfen.'), { statusCode: 409 }));
  const applied = await review();
  fireEvent.click(screen.getByRole('button', { name: 'Gespeicherten Nachweis übernehmen' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Vorgangsstand neu laden' }));
  await waitFor(() => expect(applied).toHaveBeenCalledWith(expect.objectContaining({ revision: 7 })));
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(api.get).toHaveBeenCalledWith('/integration-connections/c-a/runs/run-a');
});

it('paginates attempts in both directions using opaque encoded cursors', async () => {
  api.get.mockImplementation(url => {
    if (url.includes('cursor=older%2F%2B%3D')) return Promise.resolve({ items: [{ ...attempt, id: 'attempt-old', number: 0 }], total: 2, next_cursor: null });
    return Promise.resolve({ items: [attempt], total: 2, next_cursor: 'older/+=' });
  });
  render(<ConnectionEvidencePanel connectionId="c-a" run={run} onApplied={vi.fn()} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Ältere Nachweise' }));
  await screen.findByRole('button', { name: /Versuch 0/ });
  fireEvent.click(screen.getByRole('button', { name: 'Neuere Nachweise' }));
  await screen.findByRole('button', { name: /Versuch 1/ });
  expect(api.get.mock.calls.map(([url]) => url)).toEqual([
    '/integration-connections/c-a/runs/run-a/attempts?limit=25',
    '/integration-connections/c-a/runs/run-a/attempts?limit=25&cursor=older%2F%2B%3D',
    '/integration-connections/c-a/runs/run-a/attempts?limit=25',
  ]);
});

it('keeps proof viewing available to read-only users and hides reconciliation', async () => {
  access.write = false;
  render(<ConnectionEvidencePanel connectionId="c-a" run={run} onApplied={vi.fn()} />);
  fireEvent.click(await screen.findByRole('button', { name: /Versuch 1: Verspäteter Nachweis/ }));
  await screen.findByText('1'.repeat(64));
  expect(screen.queryByLabelText('Begründung des Abgleichs')).not.toBeInTheDocument();
  expect(api.post).not.toHaveBeenCalled();
});

it('ignores a reconciliation response after the proof panel was unmounted', async () => {
  const pending = deferred(); const applied = vi.fn(); api.post.mockReturnValue(pending.promise);
  await review(applied); fireEvent.click(screen.getByRole('button', { name: 'Gespeicherten Nachweis übernehmen' }));
  cleanup(); await act(async () => pending.resolve({ ...run, revision: 4 }));
  expect(applied).not.toHaveBeenCalled();
});

it('retries an emergency stop with exactly the same command and never touches credentials', async () => {
  api.patch.mockRejectedValueOnce(new Error('Deaktivierungsantwort fehlt.')).mockResolvedValueOnce({ ...connection, revision: 2, enabled: false });
  const changed = vi.fn(); render(<ConnectionEmergencyStop connection={connection} onChanged={changed} />);
  fireEvent.click(screen.getByRole('button', { name: 'Verbindung sicher deaktivieren' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Deaktivierung abgleichen' }));
  await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
  expect(api.patch.mock.calls[1]).toEqual(api.patch.mock.calls[0]);
  expect(Object.keys(api.patch.mock.calls[0][1]).sort()).toEqual(['base_revision', 'enabled', 'idempotency_key']);
});

it('does not classify a rejected oversized emergency stop as an uncertain outcome', async () => {
  api.patch.mockRejectedValue(Object.assign(new Error('Anfrage abgewiesen.'), { statusCode: 413 }));
  render(<ConnectionEmergencyStop connection={connection} onChanged={vi.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: 'Verbindung sicher deaktivieren' }));
  await screen.findByRole('alert');
  expect(screen.getByRole('button', { name: 'Verbindung sicher deaktivieren' })).toBeEnabled();
  expect(screen.queryByRole('button', { name: 'Deaktivierung abgleichen' })).not.toBeInTheDocument();
});

it('reloads only metadata after a stop revision conflict and uses the refreshed revision on a new stop', async () => {
  api.patch.mockRejectedValueOnce(Object.assign(new Error('Stand geändert.'), { statusCode: 409 }))
    .mockResolvedValueOnce({ ...connection, revision: 8, enabled: false });
  function CurrentConnection() {
    const [value, setValue] = useState(connection);
    return <ConnectionEmergencyStop connection={value} onChanged={setValue} />;
  }
  render(<CurrentConnection />);
  fireEvent.click(screen.getByRole('button', { name: 'Verbindung sicher deaktivieren' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Verbindungsstand neu laden' }));
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Verbindungsstand neu laden' })).not.toBeInTheDocument());
  fireEvent.click(screen.getByRole('button', { name: 'Verbindung sicher deaktivieren' }));
  await screen.findByRole('button', { name: 'Verbindung ist deaktiviert' });
  expect(api.patch.mock.calls[1][1].base_revision).toBe(7);
  expect(api.patch.mock.calls[1][1].idempotency_key).not.toBe(api.patch.mock.calls[0][1].idempotency_key);
  expect(api.get).toHaveBeenCalledWith('/integration-connections/c-a/state');
});

it('does not accept a malformed stop acknowledgement as success', async () => {
  api.patch.mockResolvedValue({ id: 'c-a', enabled: false });
  const changed = vi.fn(); render(<ConnectionEmergencyStop connection={connection} onChanged={changed} />);
  fireEvent.click(screen.getByRole('button', { name: 'Verbindung sicher deaktivieren' }));
  await screen.findByRole('button', { name: 'Deaktivierung abgleichen' });
  expect(changed).not.toHaveBeenCalled();
});

it('does not offer an emergency metadata write to a read-only role', () => {
  access.write = false; render(<ConnectionEmergencyStop connection={connection} onChanged={vi.fn()} />);
  expect(screen.getByRole('button', { name: 'Verbindung sicher deaktivieren' })).toBeDisabled();
  expect(api.patch).not.toHaveBeenCalled();
});

it('handles synchronous session failure before loading the attempt list', async () => {
  api.captureSession.mockImplementation(() => { throw Object.assign(new Error('changed'), { code: 'SESSION_CHANGED' }); });
  render(<ConnectionEvidencePanel connectionId="c-a" run={run} onApplied={vi.fn()} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Die Sitzung wurde geändert. Bitte erneut anmelden.');
  expect(api.get).not.toHaveBeenCalled();
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
  expect(screen.queryByText(/Ausführungsnachweise/)).not.toBeInTheDocument();
});

it('clears the old attempt view when synchronous proof session capture fails', async () => {
  render(<ConnectionEvidencePanel connectionId="c-a" run={run} onApplied={vi.fn()} />);
  const item = await screen.findByRole('button', { name: /Versuch 1: Verspäteter Nachweis/ });
  api.captureSession.mockImplementation(() => { throw Object.assign(new Error('changed'), { code: 'SESSION_CHANGED' }); });
  fireEvent.click(item);
  expect(await screen.findByRole('alert')).toHaveTextContent('Die Sitzung wurde geändert. Bitte erneut anmelden.');
  expect(api.get).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole('button', { name: /Versuch 1/ })).not.toBeInTheDocument();
  expect(screen.queryByText('1'.repeat(64))).not.toBeInTheDocument();
});

it('clears a reviewed draft instead of submitting it when reconciliation session capture fails', async () => {
  await review();
  api.captureSession.mockImplementation(() => { throw Object.assign(new Error('changed'), { code: 'SESSION_CHANGED' }); });
  fireEvent.click(screen.getByRole('button', { name: 'Gespeicherten Nachweis übernehmen' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Die Sitzung wurde geändert. Bitte erneut anmelden.');
  expect(api.post).not.toHaveBeenCalled();
  expect(screen.queryByDisplayValue('Nachweis beim Anbieter geprüft.')).not.toBeInTheDocument();
});

it('reports synchronous emergency-stop session failure and does not leave a busy or retryable command', async () => {
  api.captureSession.mockImplementation(() => { throw Object.assign(new Error('changed'), { code: 'SESSION_CHANGED' }); });
  render(<ConnectionEmergencyStop connection={connection} onChanged={vi.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: 'Verbindung sicher deaktivieren' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Die Sitzung wurde geändert. Bitte erneut anmelden.');
  expect(screen.getByRole('button', { name: 'Verbindung sicher deaktivieren' })).toBeDisabled();
  expect(api.patch).not.toHaveBeenCalled();
  expect(screen.queryByRole('button', { name: 'Deaktivierung abgleichen' })).not.toBeInTheDocument();
});
