import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '../api';
import ReminderPlanner from '../features/communication/ReminderPlanner';
import MessagingSection from '../pages/settings/MessagingSection';

const identity = vi.hoisted(() => ({ owner: 'reader-a' }));
vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn(), captureSession: vi.fn(() => () => {}) } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: identity.owner, role: 'readonly', email: 'self@example.test' } }) }));
vi.mock('../contexts/PreferencesContext', () => ({ usePreferences: () => ({ prefs: { reminder_channel: 'in_app', reminder_time: '09:00', reminder_days: '7' } }) }));
vi.mock('../pages/settings/SettingsCatalogue', () => ({ SettingField: () => null }));
const original = { id: 'reminder-a', revision: 7, status: 'scheduled', due_at: '2027-07-15T06:30:00+00:00',
  channel: 'whatsapp_web', recipient: '+491701234567', message: 'Privater Erinnerungstext', source_kind: 'task', source_id: 'task-a',
  source: { title: 'Private Frist Stuttgart', href: '/tasks?focus_id=task-a' } };
let stored;
beforeEach(() => {
  vi.clearAllMocks(); identity.owner = 'reader-a'; stored = original; api.captureSession.mockReturnValue(() => {});
  api.get.mockImplementation(path => Promise.resolve(path === '/auth/users/me/settings' ? { items: [] }
    : { items: identity.owner === 'reader-a' ? [stored] : [], total: identity.owner === 'reader-a' ? 1 : 0, next_offset: null }));
});
afterEach(cleanup);
const settings = () => render(<MemoryRouter><MessagingSection /></MemoryRouter>);

it('handles synchronous session capture failure in both settings readers without crashing or loading private data', async () => {
  api.captureSession.mockImplementation(() => {
    window.dispatchEvent(new Event('workspace-logout'));
    throw Object.assign(new Error('Die Sitzung wurde geändert.'), { code: 'SESSION_CHANGED' });
  });
  settings();
  await waitFor(() => expect(screen.getAllByRole('alert').every(node => /Sitzung wurde geändert/.test(node.textContent))).toBe(true));
  expect(api.captureSession).toHaveBeenCalledTimes(2);
  expect(api.get).not.toHaveBeenCalled(); expect(api.post).not.toHaveBeenCalled();
  expect(screen.queryByText(original.source.title)).not.toBeInTheDocument();
  expect(screen.queryByText(original.message)).not.toBeInTheDocument();
});

it('lets a read-only reader move an existing plan using its stored Berlin time and revision, without creating another plan', async () => {
  api.post.mockImplementation(async () => {
    stored = { ...original, revision: 8, due_at: '2027-07-31T09:15:00+00:00' };
    return stored;
  });
  settings();
  fireEvent.click(await screen.findByRole('button', { name: 'Zeitpunkt ändern' }));
  const dialog = screen.getByRole('dialog', { name: 'Erinnerungszeitpunkt ändern' });
  expect(within(dialog).getByLabelText('Datum und Uhrzeit (Europe/Berlin)')).toHaveValue('2027-07-15T08:30');
  expect(within(dialog).queryByLabelText('Erinnerungsweg')).not.toBeInTheDocument();
  expect(within(dialog).queryByLabelText('Empfänger der Erinnerung')).not.toBeInTheDocument();
  expect(within(dialog).queryByLabelText('Erinnerungstext')).not.toBeInTheDocument();
  fireEvent.change(within(dialog).getByLabelText('Datum und Uhrzeit (Europe/Berlin)'), { target: { value: '2027-07-31T11:15' } });
  const submit = within(dialog).getByRole('button', { name: 'Zeitpunkt speichern' });
  fireEvent.click(submit); fireEvent.click(submit);
  expect(await within(dialog).findByRole('status')).toHaveTextContent('Erinnerung gespeichert: 31.07.2027');
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(api.post.mock.calls[0]).toEqual(['/notifications/reminders/reminder-a/command', {
    action: 'reschedule', base_revision: 7, local_due_at: '2027-07-31T11:15', idempotency_key: expect.any(String),
  }]);
  expect(api.post.mock.calls.some(([path]) => path === '/notifications/reminders')).toBe(false);
});

it.each([409, undefined])('preserves the edited date and original command after a rejected or uncertain response (%s)', async code => {
  const failure = Object.assign(new Error(code === 409 ? 'Erinnerung wurde gleichzeitig geändert' : 'Antwort nicht bestätigt'), { statusCode: code });
  api.post.mockRejectedValue(failure); const onSaved = vi.fn();
  render(<ReminderPlanner plan={original} sourceTitle={original.source.title} onSaved={onSaved} onClose={vi.fn()} />);
  const input = screen.getByLabelText('Datum und Uhrzeit (Europe/Berlin)');
  fireEvent.change(input, { target: { value: '2027-08-02T10:45' } });
  fireEvent.click(screen.getByRole('button', { name: 'Zeitpunkt speichern' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(failure.message);
  expect(input).toHaveValue('2027-08-02T10:45'); expect(onSaved).not.toHaveBeenCalled();
  expect(screen.queryByText(/Erinnerung gespeichert/)).not.toBeInTheDocument();
  const command = api.post.mock.calls[0][1];
  fireEvent.click(screen.getByRole('button', { name: 'Zeitpunkt speichern' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2));
  expect(api.post.mock.calls[1][1]).toEqual(command);
  expect(command.base_revision).toBe(7); expect(onSaved).not.toHaveBeenCalled();
});

it('closes the personal editor on account change and ignores its late save result without exposing private fields', async () => {
  let resolve; api.post.mockImplementationOnce(() => new Promise(yes => { resolve = yes; }));
  settings();
  fireEvent.click(await screen.findByRole('button', { name: 'Zeitpunkt ändern' }));
  fireEvent.change(screen.getByLabelText('Datum und Uhrzeit (Europe/Berlin)'), { target: { value: '2027-08-02T10:45' } });
  fireEvent.click(screen.getByRole('button', { name: 'Zeitpunkt speichern' }));
  const changed = vi.fn(); window.addEventListener('reminder-change', changed);
  try {
    act(() => { identity.owner = 'reader-b'; window.dispatchEvent(new Event('workspace-owner')); });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await act(async () => resolve({ ...original, revision: 8, due_at: '2027-08-02T08:45:00+00:00' }));
    expect(changed).not.toHaveBeenCalled();
    expect(screen.queryByText('Private Frist Stuttgart')).not.toBeInTheDocument();
    expect(screen.queryByText('Privater Erinnerungstext')).not.toBeInTheDocument();
    expect(screen.queryByText('+491701234567')).not.toBeInTheDocument();
    expect(screen.queryByText(/Erinnerung gespeichert/)).not.toBeInTheDocument();
  } finally { window.removeEventListener('reminder-change', changed); }
});
