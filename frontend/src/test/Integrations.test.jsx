import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import Integrations from '../pages/Integrations';
import { api } from '../api';

const access = vi.hoisted(() => ({ canWrite: true }));
vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: () => undefined }) }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => access.canWrite }));

const email = {
  id: 'email', name: 'E-Mail (SMTP)', description: 'SMTP', category: 'communication', enabled: true,
  configured: true, message: 'Konfiguriert (Verbindung ungeprüft)', health: { status: 'configured' },
  config: { smtp_host: 'mail.example.test', smtp_password: '***' }, capabilities: [],
  config_fields: [
    { key: 'smtp_host', label: 'SMTP-Server', type: 'string' },
    { key: 'smtp_password', label: 'SMTP-Passwort', type: 'string', secret: true },
    { key: 'smtp_port', label: 'SMTP-Port', type: 'integer', default: 587 },
  ],
  actions: [
    { id: 'check_connection', label: 'Verbindung prüfen (ohne Versand)', inputs: [] },
    { id: 'send', label: 'E-Mail versenden', inputs: [
      { key: 'recipient', label: 'Empfänger', type: 'string', required: true, format: 'email' },
      { key: 'subject', label: 'Betreff', type: 'string' },
    ] },
  ],
};

beforeEach(() => {
  vi.resetAllMocks(); access.canWrite = true;
  api.get.mockResolvedValue({ integrations: [email] });
  api.put.mockResolvedValue({ config: email.config });
  api.patch.mockResolvedValue({});
  api.post.mockResolvedValue({ success: true, message: 'SMTP geprüft' });
});
afterEach(cleanup);

it('shows a load failure and retries the list', async () => {
  api.get.mockRejectedValueOnce(new Error('Server nicht erreichbar'));
  render(<Integrations />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Server nicht erreichbar');
  fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
  expect(await screen.findByText('E-Mail (SMTP)')).toBeInTheDocument();
});

it('saves edited configuration without submitting the masked secret', async () => {
  render(<Integrations />);
  const host = await screen.findByLabelText('SMTP-Server');
  fireEvent.change(host, { target: { value: 'new.example.test' } });
  fireEvent.click(screen.getByRole('button', { name: 'Konfiguration speichern' }));
  await waitFor(() => expect(api.put).toHaveBeenCalledWith('/integrations/email/config', {
    config: { smtp_host: 'new.example.test', smtp_port: 587 },
  }));
  expect(screen.getByLabelText('SMTP-Passwort')).toHaveValue('');
});

it('checks the connection without inventing a recipient, then sends to the chosen recipient', async () => {
  render(<Integrations />);
  fireEvent.click(await screen.findByRole('button', { name: 'Aktion ausführen' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/integrations/email/run', { payload: { action: 'check_connection' } }));
  fireEvent.change(screen.getByLabelText('Aktion'), { target: { value: 'send' } });
  expect(screen.getByLabelText('Empfänger')).toHaveValue('');
  expect(screen.getByRole('button', { name: 'E-Mail versenden' })).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Empfänger'), { target: { value: 'chosen@example.test' } });
  fireEvent.click(screen.getByRole('button', { name: 'E-Mail versenden' }));
  await waitFor(() => expect(api.post).toHaveBeenLastCalledWith('/integrations/email/run', {
    payload: { action: 'send', recipient: 'chosen@example.test' },
  }));
});

it('shows failed action details and can retry the same chosen action', async () => {
  api.post.mockResolvedValueOnce({ success: false, message: 'SMTP abgelehnt', details: { code: 'transport_error' } });
  render(<Integrations />);
  fireEvent.click(await screen.findByRole('button', { name: 'Aktion ausführen' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('SMTP abgelehnt');
  fireEvent.click(screen.getByRole('button', { name: 'Aktion erneut versuchen' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2));
});

it('hides configuration and execution controls from readers', async () => {
  access.canWrite = false;
  render(<Integrations />);
  expect(await screen.findByText('E-Mail (SMTP)')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Konfiguration speichern' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Aktion ausführen' })).not.toBeInTheDocument();
  expect(screen.queryByLabelText('SMTP-Passwort')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Deaktivieren' })).not.toBeInTheDocument();
});

it('does not offer an automatic resend after an ambiguous HTTP failure', async () => {
  api.post.mockRejectedValueOnce(new Error('Verbindung abgebrochen'));
  render(<Integrations />);
  fireEvent.change(await screen.findByLabelText('Aktion'), { target: { value: 'send' } });
  fireEvent.change(screen.getByLabelText('Empfänger'), { target: { value: 'chosen@example.test' } });
  fireEvent.click(screen.getByRole('button', { name: 'E-Mail versenden' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Verbindung abgebrochen');
  expect(screen.queryByRole('button', { name: 'Aktion erneut versuchen' })).not.toBeInTheDocument();
});

it('shows damaged saved state and blocks configuration controls', async () => {
  api.get.mockResolvedValue({ integrations: [{ ...email, persistence_error: 'Gespeicherte Konfiguration beschädigt' }] });
  render(<Integrations />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Konfiguration beschädigt');
  expect(screen.getByRole('button', { name: 'Konfiguration speichern' })).toBeDisabled();
});

it('pages through saved history and shows history errors with a retry', async () => {
  api.get.mockImplementation(path => path === '/integrations'
    ? Promise.resolve({ integrations: [email] })
    : Promise.resolve({ items: [{ id: 'run', created_at: '2026-10-07T10:00:00Z', success: false, message: 'Ergebnis unbestätigt' }], total: 21, skip: 0, limit: 20 }));
  render(<Integrations />);
  fireEvent.click(await screen.findByRole('button', { name: 'Verlauf anzeigen' }));
  expect(await screen.findByText('Ergebnis unbestätigt')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Weitere Einträge' }));
  await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/integrations/email/history?limit=20&skip=20'));
  api.get.mockRejectedValueOnce(new Error('Journal nicht erreichbar'));
  fireEvent.click(screen.getByRole('button', { name: 'Vorherige Einträge' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Journal nicht erreichbar');
  fireEvent.click(screen.getByRole('button', { name: 'Verlauf erneut laden' }));
  await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/integrations/email/history?limit=20&skip=0'));
});
