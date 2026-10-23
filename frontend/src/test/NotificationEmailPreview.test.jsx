import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import NotificationEmailPreview from '../components/NotificationEmailPreview';
import { api } from '../api';
import { setWorkspaceOwner } from '../utils/workspaceIdentity';

vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn(), captureSession: vi.fn(() => () => {}) } }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => true }));
const notice = { id: 'note-a', title: 'Fällige Aufgabe', email_eligible: true, target: { revision: 'source-r1' } };
const item = { id: 'email-a', to: ['self@example.test'], subject: 'Fällige Aufgabe', body: 'Quellinhalt', revision: 1, mime_sha256: 'a'.repeat(64), state: 'preview' };
beforeEach(() => {
  vi.clearAllMocks(); sessionStorage.clear(); setWorkspaceOwner('mail-reader');
  api.get.mockResolvedValue({ items: [{ id: 'connection-a', revision: 3, name: 'Verwaltung' }], next_cursor: null });
  api.post.mockResolvedValue(item);
});
afterEach(cleanup);

it('creates only a preview until the user explicitly releases the exact MIME', async () => {
  render(<NotificationEmailPreview notice={notice} />);
  expect(api.get).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Persönliche E-Mail-Vorschau öffnen' }));
  await screen.findByLabelText('E-Mail-Verbindung');
  expect(api.post).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'E-Mail-Vorschau erstellen' }));
  expect(await screen.findByText('Empfänger: self@example.test · Status: preview')).toBeInTheDocument();
  expect(api.post.mock.calls[0]).toEqual(['/notifications/note-a/email-preview', expect.objectContaining({ connection_id: 'connection-a', config_revision: 3, source_revision: 'source-r1' })]);
  expect(api.post).toHaveBeenCalledTimes(1);
  api.post.mockResolvedValue({ ...item, revision: 2, state: 'ready' });
  fireEvent.click(screen.getByRole('button', { name: 'Persönlichen E-Mail-Versand ausdrücklich freigeben' }));
  expect(await screen.findByRole('status')).toHaveTextContent('Versand ausdrücklich beauftragt');
  expect(api.post.mock.calls[1]).toEqual(['/messages/communication/email-a/confirm', expect.objectContaining({ base_revision: 1, mime_sha256: item.mime_sha256, confirmed: true })]);
});

it('keeps the exact preview command after a lost answer and after remount', async () => {
  api.post.mockRejectedValueOnce(new Error('Offline'));
  const first = render(<NotificationEmailPreview notice={notice} />);
  fireEvent.click(screen.getByRole('button', { name: 'Persönliche E-Mail-Vorschau öffnen' }));
  await screen.findByLabelText('E-Mail-Verbindung');
  fireEvent.click(screen.getByRole('button', { name: 'E-Mail-Vorschau erstellen' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Offline');
  const command = api.post.mock.calls[0][1];
  first.unmount();
  render(<NotificationEmailPreview notice={notice} />);
  fireEvent.click(screen.getByRole('button', { name: 'Persönliche E-Mail-Vorschau öffnen' }));
  await screen.findByLabelText('E-Mail-Verbindung');
  fireEvent.click(screen.getByRole('button', { name: 'E-Mail-Vorschau erstellen' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2));
  expect(api.post.mock.calls[1][1]).toEqual(command);
});

it('reuses an uncertain release command and recovers its status without another send', async () => {
  const first = render(<NotificationEmailPreview notice={notice} />);
  fireEvent.click(screen.getByRole('button', { name: 'Persönliche E-Mail-Vorschau öffnen' }));
  await screen.findByLabelText('E-Mail-Verbindung');
  fireEvent.click(screen.getByRole('button', { name: 'E-Mail-Vorschau erstellen' }));
  await screen.findByText('Quellinhalt');
  api.post.mockRejectedValueOnce(new Error('Antwort verloren')).mockResolvedValue({ ...item, state: 'ready', revision: 2 });
  fireEvent.click(screen.getByRole('button', { name: 'Persönlichen E-Mail-Versand ausdrücklich freigeben' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Antwort verloren');
  const command = api.post.mock.calls[1][1];
  fireEvent.click(screen.getByRole('button', { name: 'Persönlichen E-Mail-Versand ausdrücklich freigeben' }));
  await screen.findByRole('status');
  expect(api.post.mock.calls[2][1]).toEqual(command);
  first.unmount();
  api.get.mockResolvedValue({ ...item, state: 'accepted', revision: 5 });
  render(<NotificationEmailPreview notice={notice} />);
  fireEvent.click(screen.getByRole('button', { name: 'Persönliche E-Mail-Vorschau öffnen' }));
  expect(await screen.findByRole('status')).toHaveTextContent('Zustellung ist nicht nachgewiesen');
  expect(api.post).toHaveBeenCalledTimes(3);
});

it('never offers an email action for a blocked or archived hint', async () => {
  const view = render(<NotificationEmailPreview notice={{ ...notice, email_eligible: false }} />);
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
  view.rerender(<NotificationEmailPreview notice={{ ...notice, archived_at: '2026-10-16' }} />);
  await act(async () => {});
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
  expect(api.post).not.toHaveBeenCalled();
});

it('requires an explicit retry for a confirmed failure and rechecks a rejected source preview', async () => {
  api.post.mockRejectedValueOnce(Object.assign(new Error('Quelle geändert'), { statusCode: 409 }));
  render(<NotificationEmailPreview notice={notice} />);
  fireEvent.click(screen.getByRole('button', { name: 'Persönliche E-Mail-Vorschau öffnen' }));
  await screen.findByLabelText('E-Mail-Verbindung');
  fireEvent.click(screen.getByRole('button', { name: 'E-Mail-Vorschau erstellen' }));
  await screen.findByRole('alert');
  const rejected = api.post.mock.calls[0][1];
  api.get.mockResolvedValueOnce({ source: { revision: 'source-r2' } }).mockResolvedValueOnce({ items: [{ id: 'connection-a', revision: 4, name: 'Verwaltung' }] });
  fireEvent.click(screen.getByRole('button', { name: 'Abgewiesene Vorschau verwerfen und aktuellen Stand prüfen' }));
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  api.post.mockResolvedValueOnce({ ...item, state: 'failed', revision: 3 });
  fireEvent.click(screen.getByRole('button', { name: 'E-Mail-Vorschau erstellen' }));
  await screen.findByRole('button', { name: 'Nach Prüfung ausdrücklich erneut freigeben' });
  expect(api.post.mock.calls[1][1]).toEqual(expect.objectContaining({ source_revision: 'source-r2', config_revision: 4 }));
  expect(api.post.mock.calls[1][1].idempotency_key).not.toBe(rejected.idempotency_key);
  expect(api.post).toHaveBeenCalledTimes(2);
  api.post.mockResolvedValueOnce({ ...item, state: 'ready', revision: 4 });
  fireEvent.click(screen.getByRole('button', { name: 'Nach Prüfung ausdrücklich erneut freigeben' }));
  await screen.findByRole('status');
  expect(api.post.mock.calls[2][0]).toBe('/messages/communication/email-a/retry');
});
