import { useState } from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import useWorkspaceViewState from '../hooks/useWorkspaceViewState';

const mock = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), command: vi.fn() }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'owner' } }) }));
vi.mock('../utils/workspaceClient', () => ({ workspace: mock }));

function View({ id }) {
  const [state, setState] = useState({ sort_key: 'name' });
  const saved = useWorkspaceViewState('table:properties', state, setState);
  return <section aria-label={id}><input aria-label={`Sortierung ${id}`} value={state.sort_key}
    onChange={event => setState({ sort_key: event.target.value })} />
    {saved.error && <p role="alert">{saved.error}</p>}
    {saved.error && <button onClick={saved.conflict ? saved.reload : saved.retry}>{saved.conflict ? `Serveransicht ${id} laden` : `Speicherung ${id} wiederholen`}</button>}
  </section>;
}

let server;
beforeEach(() => {
  vi.useFakeTimers(); vi.resetAllMocks();
  server = { revision: 1, state: { sort_key: 'name' } };
  mock.command.mockImplementation(() => crypto.randomUUID());
  mock.get.mockImplementation(async () => structuredClone(server));
  const receipts = new Map();
  mock.put.mockImplementation(async (_type, _context, command) => {
    if (receipts.has(command.idempotency_key)) return structuredClone(receipts.get(command.idempotency_key));
    if (command.base_revision !== server.revision) throw Object.assign(new Error('Konflikt'), { statusCode: 409 });
    server = { revision: server.revision + 1, state: structuredClone(command.state) };
    receipts.set(command.idempotency_key, structuredClone(server));
    return structuredClone(server);
  });
});
afterEach(() => { cleanup(); vi.useRealTimers(); });
const tick = async () => act(async () => { await vi.advanceTimersByTimeAsync(1000); });

describe('recoverable table view persistence', () => {
  it('shows a real two-tab conflict and resumes from the explicitly reloaded server revision', async () => {
    render(<><View id="A" /><View id="B" /></>);
    await tick(); expect(mock.put).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('Sortierung A'), { target: { value: 'amount' } });
    await tick(); expect(server.revision).toBe(2);
    fireEvent.change(screen.getByLabelText('Sortierung B'), { target: { value: 'booking_date' } });
    await tick(); expect(screen.getByRole('alert')).toHaveTextContent('anderen Fenster');
    expect(server.state.sort_key).toBe('amount');
    fireEvent.click(screen.getByRole('button', { name: 'Serveransicht B laden' }));
    await tick(); expect(screen.getByLabelText('Sortierung B')).toHaveValue('amount');
    fireEvent.change(screen.getByLabelText('Sortierung B'), { target: { value: 'booking_date' } });
    await tick();
    expect(server).toEqual({ revision: 3, state: { sort_key: 'booking_date' } });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('retries a lost response with the original durable command and then saves further edits', async () => {
    render(<View id="A" />); await tick();
    const commit = mock.put.getMockImplementation();
    mock.put.mockImplementationOnce(async (...args) => {
      await commit(...args);
      throw Object.assign(new Error('Antwort nach erfolgreichem Speichern verloren'), { statusCode: 503 });
    });
    fireEvent.change(screen.getByLabelText('Sortierung A'), { target: { value: 'amount' } });
    await tick(); expect(screen.getByRole('alert')).toHaveTextContent('nicht gespeichert');
    const command = mock.put.mock.calls[0][2];
    fireEvent.click(screen.getByRole('button', { name: 'Speicherung A wiederholen' }));
    await tick(); expect(mock.put.mock.calls[1][2]).toEqual(command);
    fireEvent.change(screen.getByLabelText('Sortierung A'), { target: { value: 'booking_date' } });
    await tick(); expect(server.revision).toBe(3); expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('does not report a conflict when another tab already saved exactly the desired state', async () => {
    render(<><View id="A" /><View id="B" /></>); await tick();
    fireEvent.change(screen.getByLabelText('Sortierung A'), { target: { value: 'amount' } }); await tick();
    fireEvent.change(screen.getByLabelText('Sortierung B'), { target: { value: 'amount' } }); await tick();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Sortierung B'), { target: { value: 'booking_date' } }); await tick();
    expect(server.revision).toBe(3);
  });
});
