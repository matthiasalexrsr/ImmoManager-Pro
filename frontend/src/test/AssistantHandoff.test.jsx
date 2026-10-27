import { useState } from 'react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { fireEvent, render, screen, waitFor, act } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import useAssistantHandoff from '../hooks/useAssistantHandoff';

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), owner: 'owner-a' }));
vi.mock('../api', () => ({ api: { get: mocks.get, post: mocks.post } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: mocks.owner } }) }));

const proposal = { id: 'proposal-a', revision: 2, state: 'applied', conversation_id: 'chat-a',
  payload: { kind: 'task', values: { title: 'Heizung anrufen' } } };
function Probe() {
  const [initial, setInitial] = useState(null);
  const [result, setResult] = useState('');
  const [failure, setFailure] = useState('');
  const handoff = useAssistantHandoff('task', setInitial);
  const location = useLocation();
  return <><p>{initial?.title || 'Noch kein Formular'}</p><p>{result}</p><p>{failure}</p><p>{handoff.error}</p>
    <p>{location.search}</p><p>{handoff.returnHref}</p>
    <button onClick={async () => { try { const saved = await handoff.save({ title: initial.title, due_date: '', property_id: '' }); setResult(saved.record.id); } catch (error) { setFailure(error.message); } }}>Speichern</button>
    <button onClick={handoff.clear}>Schließen</button></>;
}
function show() { return render(<MemoryRouter initialEntries={['/tasks?assistant_proposal=proposal-a']}><Probe /></MemoryRouter>); }

beforeEach(() => { vi.clearAllMocks(); mocks.owner = 'owner-a'; mocks.get.mockResolvedValue(proposal); });
describe('private proposal in a final domain form', () => {
  it('reloads an authoritative proposal and saves through its single-use endpoint', async () => {
    mocks.post.mockResolvedValue({ proposal: { ...proposal, state: 'saved', revision: 3 }, record: { id: 'task-a' } });
    show(); await screen.findByText('Heizung anrufen');
    fireEvent.click(screen.getByText('Speichern'));
    await screen.findByText('task-a');
    expect(mocks.post).toHaveBeenCalledWith('/assistant/proposals/proposal-a/save', {
      expected_revision: 2, idempotency_key: expect.any(String), values: { title: 'Heizung anrufen' },
    });
    expect(screen.getByText('/assistant?conversation=chat-a')).toBeInTheDocument();
  });
  it('retries an unknown success with the identical command instead of an ordinary record POST', async () => {
    mocks.post.mockRejectedValueOnce(new Error('Verbindung verloren')).mockResolvedValueOnce({ proposal: { ...proposal, state: 'saved' }, record: { id: 'task-a' } });
    show(); await screen.findByText('Heizung anrufen');
    fireEvent.click(screen.getByText('Speichern')); await screen.findByText('Verbindung verloren');
    fireEvent.click(screen.getByText('Speichern')); await screen.findByText('task-a');
    expect(mocks.post.mock.calls[1]).toEqual(mocks.post.mock.calls[0]);
  });
  it('a failed private lookup never opens or saves an unbound domain form', async () => {
    mocks.get.mockRejectedValue(new Error('Entwurf nicht vorhanden'));
    show(); await screen.findByText('Entwurf nicht vorhanden');
    expect(screen.getByText('Noch kein Formular')).toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled();
  });
  it('does not reopen a saved proposal after reload', async () => {
    mocks.get.mockResolvedValue({ ...proposal, state: 'saved', record: { id: 'task-a' } });
    show(); await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    await act(async () => {});
    expect(screen.getByText('Noch kein Formular')).toBeInTheDocument();
  });
  it('discarding the handoff removes only its URL context', async () => {
    show(); await screen.findByText('Heizung anrufen'); fireEvent.click(screen.getByText('Schließen'));
    await waitFor(() => expect(screen.queryByText('?assistant_proposal=proposal-a')).not.toBeInTheDocument());
  });
});
