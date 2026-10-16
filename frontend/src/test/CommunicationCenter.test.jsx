import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { api } from '../api';
import CommunicationCenter from '../features/communication/CommunicationCenter';

const permissions = vi.hoisted(() => ({ write: true }));
const privateDraft = vi.hoisted(() => ({ stage: vi.fn(), clear: vi.fn(), recovery: null, error: '', enabled: true, ready: true }));
vi.mock('../hooks/useEntityFormDraft', () => ({ default: () => privateDraft }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => permissions.write, useAuth: () => null }));
vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), put: vi.fn(), getBlob: vi.fn(), captureSession: vi.fn() } }));
const threads = [{ id: 'thread', subject: 'Mietvertrag', updated_at: '2026-10-16T10:00:00Z' }];
const base = '/messages/communication';
const row = { id: 'outbox', kind: 'outbound', state: 'preview', revision: 1, subject: 'Ausgewählte E-Mail', body: 'Freizugebender Inhalt', to: ['to@example.test'], cc: [], bcc: ['blind@example.test'], thread_id: 'thread', mime_sha256: 'a'.repeat(64), attachments: [], history: [] };
let items;
beforeEach(() => {
  vi.resetAllMocks(); privateDraft.clear.mockResolvedValue(); permissions.write = true; items = [row];
  api.captureSession.mockReturnValue(() => {});
  api.list.mockResolvedValue([]);
  api.get.mockImplementation(path => {
    if (path.includes('/connections/choices')) return Promise.resolve({ items: [{ id: 'connection', name: 'Verwaltung', revision: 3 }] });
    if (path.includes('kind=template')) return Promise.resolve({ items: [] });
    return Promise.resolve({ items, total: items.length });
  });
});
afterEach(cleanup);
const open = () => render(<MemoryRouter><CommunicationCenter threads={threads} /></MemoryRouter>);

it('does not send on preview or selection and requires explicit recipient confirmation', async () => {
  open(); fireEvent.click(await screen.findByRole('button', { name: /Ausgewählte E-Mail/ }));
  expect(api.post).not.toHaveBeenCalled();
  const send = screen.getByRole('button', { name: 'Versand verbindlich freigeben' });
  expect(send).toBeDisabled();
  expect(screen.getByText(/BCC: blind@example.test/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('checkbox'));
  api.post.mockResolvedValue({ ...row, state: 'ready', revision: 2 });
  fireEvent.click(send);
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
  expect(api.post.mock.calls[0][0]).toBe(`${base}/outbox/confirm`);
  expect(api.post.mock.calls[0][1]).toMatchObject({ confirmed: true, base_revision: 1, mime_sha256: row.mime_sha256 });
});

it('retains the exact command after a lost confirmation and never invents a new send', async () => {
  open(); fireEvent.click(await screen.findByRole('button', { name: /Ausgewählte E-Mail/ })); fireEvent.click(screen.getByRole('checkbox'));
  api.post.mockRejectedValueOnce(new Error('Verbindung verloren')).mockResolvedValueOnce({ ...row, state: 'ready' });
  fireEvent.click(screen.getByRole('button', { name: 'Versand verbindlich freigeben' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Speicherung abgleichen' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2));
  expect(api.post.mock.calls[1]).toEqual(api.post.mock.calls[0]);
});

it('shows unknown separately and permits only a documented reconciliation', async () => {
  items = [{ ...row, state: 'unknown' }]; open();
  fireEvent.click(await screen.findByRole('button', { name: /Ausgewählte E-Mail/ }));
  expect(screen.queryByRole('button', { name: /Versand.*freigeben|Versand.*wiederholen/ })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Annahme nachgewiesen' })).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Abgleichbeleg'), { target: { value: 'Serverprotokoll vom 16.10. bestätigt Annahme.' } });
  api.post.mockResolvedValue({ ...row, state: 'accepted' });
  fireEvent.click(screen.getByRole('button', { name: 'Annahme nachgewiesen' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
  expect(api.post.mock.calls[0][0]).toBe(`${base}/outbox/reconcile`);
});

it('enforces read-only controls while allowing history and original downloads', async () => {
  permissions.write = false; open(); fireEvent.click(await screen.findByRole('button', { name: /Ausgewählte E-Mail/ }));
  expect(screen.queryByRole('button', { name: /freigeben|entwerfen|abrufen/ })).not.toBeInTheDocument();
  expect(screen.getByText(/Nur Lesen/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Unverändertes E-Mail-Original herunterladen' })).toBeInTheDocument();
});

it('clears private content and rejects a late response after logout', async () => {
  let resolve;
  api.get.mockImplementation(path => path.includes('connections') || path.includes('template') ? Promise.resolve({ items: [] }) : new Promise(yes => { resolve = yes; }));
  open(); await waitFor(() => expect(resolve).toBeTypeOf('function'));
  act(() => window.dispatchEvent(new Event('workspace-logout')));
  await act(async () => resolve({ items: [row], total: 1 }));
  expect(screen.queryByRole('button', { name: /Ausgewählte E-Mail/ })).not.toBeInTheDocument();
});

it('saves recipient choices in a private draft without initiating SMTP', async () => {
  open(); await screen.findByRole('button', { name: /Ausgewählte E-Mail/ });
  fireEvent.change(screen.getByLabelText('Konversation'), { target: { value: 'thread' } });
  fireEvent.click(screen.getByRole('button', { name: 'E-Mail entwerfen' }));
  fireEvent.change(screen.getByLabelText('E-Mail-Verbindung'), { target: { value: 'connection' } });
  fireEvent.change(screen.getByLabelText('An', { exact: true }), { target: { value: 'one@example.test; two@example.test' } });
  fireEvent.change(screen.getByLabelText('Blindkopie (Bcc)'), { target: { value: 'blind@example.test' } });
  fireEvent.change(screen.getByLabelText('Nachricht'), { target: { value: 'Der Entwurf bleibt privat.' } });
  api.post.mockResolvedValue({ ...row, id: 'draft', kind: 'draft', state: 'draft' });
  fireEvent.click(screen.getByRole('button', { name: 'Entwurf speichern' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
  expect(api.post.mock.calls[0][0]).toBe(`${base}/drafts`);
  expect(api.post.mock.calls[0][1]).toMatchObject({ to: ['one@example.test', 'two@example.test'], bcc: ['blind@example.test'], config_revision: 3, source_revision: threads[0].updated_at });
});

it('opens a saved draft from the global list in its source conversation', async () => {
  items = [{ ...row, kind: 'draft', state: 'draft', connection_id: 'connection' }];
  open(); fireEvent.click(await screen.findByRole('button', { name: /Ausgewählte E-Mail/ }));
  expect(screen.getByLabelText('Konversation')).toHaveValue('thread');
  expect(screen.getByLabelText('Nachricht')).toHaveValue('Freizugebender Inhalt');
  expect(screen.getByRole('button', { name: 'Entwurf speichern' })).toBeInTheDocument();
});

it('inserts a versioned snippet without sending and preserves its identity in the draft', async () => {
  const originalGet = api.get.getMockImplementation();
  api.get.mockImplementation(path => path.includes('kind=template') ? Promise.resolve({ items: [{ id: 'snippet-v1', usage: 'snippet', name: 'Gruß', body: 'Mit freundlichen Grüßen' }] }) : originalGet(path));
  open(); await screen.findByRole('button', { name: /Ausgewählte E-Mail/ });
  fireEvent.change(screen.getByLabelText('Konversation'), { target: { value: 'thread' } });
  fireEvent.click(screen.getByRole('button', { name: 'E-Mail entwerfen' }));
  fireEvent.change(screen.getByLabelText('E-Mail-Verbindung'), { target: { value: 'connection' } });
  fireEvent.change(screen.getByLabelText('An', { exact: true }), { target: { value: 'one@example.test' } });
  fireEvent.change(screen.getByLabelText('Textbaustein einfügen'), { target: { value: 'snippet-v1' } });
  expect(screen.getByLabelText('Nachricht')).toHaveValue('Mit freundlichen Grüßen');
  expect(api.post).not.toHaveBeenCalled();
  api.post.mockResolvedValue({ ...row, id: 'draft', kind: 'draft', state: 'draft' });
  fireEvent.click(screen.getByRole('button', { name: 'Entwurf speichern' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
  expect(api.post.mock.calls[0][1]).toMatchObject({ snippet_ids: ['snippet-v1'], body: 'Mit freundlichen Grüßen' });
});

it('does not clear the newer crash draft when an older save succeeds', async () => {
  let resolve;
  api.post.mockReturnValue(new Promise(yes => { resolve = yes; }));
  open(); await screen.findByRole('button', { name: /Ausgewählte E-Mail/ });
  fireEvent.change(screen.getByLabelText('Konversation'), { target: { value: 'thread' } });
  fireEvent.click(screen.getByRole('button', { name: 'E-Mail entwerfen' }));
  fireEvent.change(screen.getByLabelText('E-Mail-Verbindung'), { target: { value: 'connection' } });
  fireEvent.change(screen.getByLabelText('Nachricht'), { target: { value: 'Älterer gesendeter Entwurf' } });
  fireEvent.click(screen.getByRole('button', { name: 'Entwurf speichern' }));
  fireEvent.change(screen.getByLabelText('Nachricht'), { target: { value: 'Neuere Eingabe muss bleiben' } });
  await act(async () => resolve({ ...row, id: 'saved-draft', kind: 'draft', state: 'draft' }));
  expect(screen.getByLabelText('Nachricht')).toHaveValue('Neuere Eingabe muss bleiben');
  expect(privateDraft.stage).toHaveBeenLastCalledWith(expect.objectContaining({ body: 'Neuere Eingabe muss bleiben' }));
  expect(privateDraft.clear).not.toHaveBeenCalled();
});

it('never switches back to another source on a late save response', async () => {
  let resolve;
  api.post.mockReturnValue(new Promise(yes => { resolve = yes; }));
  render(<MemoryRouter><CommunicationCenter threads={[...threads, { id: 'other', subject: 'Andere Akte', updated_at: threads[0].updated_at }]} /></MemoryRouter>);
  await screen.findByRole('button', { name: /Ausgewählte E-Mail/ });
  fireEvent.change(screen.getByLabelText('Konversation'), { target: { value: 'thread' } });
  fireEvent.click(screen.getByRole('button', { name: 'E-Mail entwerfen' }));
  fireEvent.change(screen.getByLabelText('E-Mail-Verbindung'), { target: { value: 'connection' } });
  fireEvent.change(screen.getByLabelText('Nachricht'), { target: { value: 'Früherer Vorgang' } });
  fireEvent.click(screen.getByRole('button', { name: 'Entwurf speichern' }));
  fireEvent.change(screen.getByLabelText('Konversation'), { target: { value: 'other' } });
  await act(async () => resolve({ ...row, id: 'saved-draft', kind: 'draft', state: 'draft' }));
  expect(screen.getByLabelText('Konversation')).toHaveValue('other');
  expect(screen.getByRole('heading', { name: 'Neue E-Mail' })).toBeInTheDocument();
  expect(screen.getByLabelText('Nachricht')).toHaveValue('');
});

it('clears displayed private content after a fresh read denies source access', async () => {
  open(); fireEvent.click(await screen.findByRole('button', { name: /Ausgewählte E-Mail/ }));
  expect(screen.getByText('Freizugebender Inhalt')).toBeInTheDocument();
  api.get.mockImplementation(path => path.includes('connections') || path.includes('template') ? Promise.resolve({ items: [] }) : Promise.reject(Object.assign(new Error('Zugriff entzogen'), { statusCode: 403 })));
  fireEvent.click(screen.getByRole('button', { name: 'Aktualisieren' }));
  await screen.findByText('Zugriff entzogen');
  expect(screen.queryByText('Freizugebender Inhalt')).not.toBeInTheDocument();
});

it('refreshes the selected worker result even when the visible list is stale', async () => {
  items = [{ ...row, state: 'ready', revision: 2 }];
  open(); fireEvent.click(await screen.findByRole('button', { name: /Ausgewählte E-Mail/ }));
  const previousGet = api.get.getMockImplementation();
  api.get.mockImplementation(path => path === `${base}/outbox` ? Promise.resolve({ ...row, state: 'accepted', revision: 4, history: [{ state: 'accepted', detail: 'SMTP-Annahme bestätigt' }] }) : previousGet(path));
  fireEvent.click(screen.getByRole('button', { name: 'Aktualisieren' }));
  expect(await screen.findByText('Vom Mailserver angenommen', { selector: 'strong' })).toBeInTheDocument();
  expect(screen.getByText(/SMTP-Annahme bestätigt/)).toBeInTheDocument();
});
