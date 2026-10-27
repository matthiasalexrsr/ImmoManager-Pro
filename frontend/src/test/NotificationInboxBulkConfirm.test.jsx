import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import NotificationInbox from '../components/NotificationInbox';
import { api } from '../api';

vi.mock('../api', () => ({ api: {
  get: vi.fn(), post: vi.fn(), captureSession: vi.fn(() => () => {}),
} }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'reader-1' } }) }));

const page = (snapshot = 'original-proof') => ({
  items: [{ id: 'n1', title: 'Wichtiger Hinweis', content: 'Bitte prüfen',
    created_at: '2026-10-16T10:00:00Z', target: null }],
  total: 1, unread_count: 12, snapshot, next_cursor: null,
});

beforeEach(() => {
  vi.clearAllMocks(); api.get.mockResolvedValue(page()); api.post.mockResolvedValue({ acknowledged: 12 });
});
afterEach(() => cleanup());

it('bietet eine Bestätigung mit Gesamtumfang und sendet bei Abbrechen keinen Empfangsbeleg', async () => {
  render(<MemoryRouter><NotificationInbox /></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button', { name: 'Alle berechtigten Hinweise gelesen archivieren' }));
  const prompt = screen.getByRole('group', { name: 'Sammelbestätigung' });
  expect(prompt).toHaveTextContent('12');
  expect(prompt).toHaveTextContent('unabhängig von den eingestellten Filtern');
  expect(within(prompt).getByRole('button', { name: 'Abbrechen' })).toHaveFocus();
  expect(api.post).not.toHaveBeenCalled();
  fireEvent.click(within(prompt).getByRole('button', { name: 'Abbrechen' }));
  expect(api.post).not.toHaveBeenCalled();
  expect(screen.queryByRole('group', { name: 'Sammelbestätigung' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Alle berechtigten Hinweise gelesen archivieren' })).toHaveFocus();
});

it('sendet erst nach ausdrücklicher Zusage genau den bestätigten Snapshot', async () => {
  render(<MemoryRouter><NotificationInbox compact /></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button', { name: 'Alle berechtigten Hinweise gelesen archivieren' }));
  expect(api.post).not.toHaveBeenCalled();
  fireEvent.click(within(screen.getByRole('group', { name: 'Sammelbestätigung' }))
    .getByRole('button', { name: '12 Hinweise jetzt archivieren' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
  expect(api.post).toHaveBeenCalledWith('/notifications/all/receipt',
    expect.objectContaining({ action: 'read_all', snapshot: 'original-proof' }));
});

it('ein abgelehnter Beleg wird nicht doppelt versendet und ein erneuter Versuch verwendet denselben Befehl', async () => {
  api.post.mockRejectedValue(new Error('Bestätigung offline'));
  render(<MemoryRouter><NotificationInbox /></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button', { name: 'Alle berechtigten Hinweise gelesen archivieren' }));
  const confirm = within(screen.getByRole('group', { name: 'Sammelbestätigung' }))
    .getByRole('button', { name: '12 Hinweise jetzt archivieren' });
  fireEvent.click(confirm);
  fireEvent.click(confirm);
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
  expect(await screen.findByRole('alert')).toHaveTextContent('Bestätigung offline');
  expect(screen.getByText('Wichtiger Hinweis')).toBeInTheDocument();
  const previous = api.post.mock.calls[0][1];
  fireEvent.click(screen.getByRole('button', { name: 'Alle berechtigten Hinweise gelesen archivieren' }));
  fireEvent.click(within(screen.getByRole('group', { name: 'Sammelbestätigung' }))
    .getByRole('button', { name: '12 Hinweise jetzt archivieren' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2));
  expect(api.post.mock.calls[1][1]).toEqual(previous);
});


it('schließt die Bestätigung per Escape ohne Aktion und stellt den Fokus wieder her', async () => {
  render(<MemoryRouter><NotificationInbox /></MemoryRouter>);
  const start = await screen.findByRole('button', { name: 'Alle berechtigten Hinweise gelesen archivieren' });
  start.focus();
  fireEvent.click(start);
  const cancel = within(screen.getByRole('group', { name: 'Sammelbestätigung' }))
    .getByRole('button', { name: 'Abbrechen' });
  expect(cancel).toHaveFocus();
  fireEvent.keyDown(cancel, { key: 'Escape' });
  expect(screen.queryByRole('group', { name: 'Sammelbestätigung' })).not.toBeInTheDocument();
  expect(start).toHaveFocus();
  expect(api.post).not.toHaveBeenCalled();
});

it('verhindert einen Sammelauftrag, wenn der bestätigte Server-Snapshot inzwischen gewechselt hat', async () => {
  api.get.mockResolvedValueOnce(page('alter-snapshot')).mockResolvedValue({
    ...page('neuer-snapshot'),
    items: [{ ...page().items[0], title: 'Neue Vorschau' }],
  });
  render(<MemoryRouter><NotificationInbox /></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button', { name: 'Alle berechtigten Hinweise gelesen archivieren' }));
  const group = screen.getByRole('group', { name: 'Sammelbestätigung' });
  const confirm = within(group).getByRole('button', { name: '12 Hinweise jetzt archivieren' });
  expect(confirm).toBeEnabled();
  fireEvent(window, new Event('focus'));
  await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
  await screen.findByText('Neue Vorschau');
  // Refresh temporarily unmounts the page; query the *new* confirmation
  // element, not the detached DOM node from before the server request.
  const updated = screen.getByRole('group', { name: 'Sammelbestätigung' });
  expect(within(updated).getByRole('alert')).toHaveTextContent('Vorschau hat sich geändert');
  const confirmUpdated = within(updated).getByRole('button', { name: '12 Hinweise jetzt archivieren' });
  expect(confirmUpdated).toBeDisabled();
  fireEvent.click(confirmUpdated);
  expect(api.post).not.toHaveBeenCalled();
});
