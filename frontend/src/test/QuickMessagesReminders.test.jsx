import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api';
import { berlinLocal, emailClientLink, normalizedChatNumber, reminderDefault, whatsAppWebLink } from '../features/communication/quickMessages';
import QuickMessageComposer from '../features/communication/QuickMessageComposer';
import ReminderPlanner from '../features/communication/ReminderPlanner';
import ReminderArrival, { ReminderDraftLink } from '../features/communication/ReminderArrival';
import useReminders from '../features/communication/useReminders';

const identity = vi.hoisted(() => ({ owner: 'reader-a' }));
vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn(), captureSession: vi.fn(() => () => {}) } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: identity.owner, role: 'readonly', email: 'self@example.test' } }) }));
vi.mock('../contexts/PreferencesContext', () => ({ usePreferences: () => ({ prefs: { reminder_channel: 'in_app', reminder_time: '09:00', reminder_days: '7', default_message_channel: 'whatsapp_web' } }) }));
beforeEach(() => { vi.clearAllMocks(); identity.owner = 'reader-a'; api.captureSession.mockReturnValue(() => {}); api.get.mockResolvedValue({ items: [], total: 0, next_offset: null }); });
afterEach(() => { cleanup(); vi.useRealTimers(); });
const wrap = content => render(<MemoryRouter>{content}</MemoryRouter>);

describe('manual messages', () => {
  it('opens the exact WhatsAppWeb chat with independently decoded phone and Unicode text', () => {
    const text = 'Guten Tag Müller,\nBetrag 50 € & Termin?';
    const link = new URL(whatsAppWebLink('+49 (0) 170/1234567', text));
    expect(link.origin + link.pathname).toBe('https://web.whatsapp.com/send');
    expect(link.searchParams.get('phone')).toBe('491701234567');
    expect(link.searchParams.get('text')).toBe(text);
    expect(normalizedChatNumber('0043 664 1234567')).toBe('436641234567');
    for (const invalid of ['12', '+00491701234567', '++491701234567', 'Tel: 01701234567', '4917<script>123']) expect(whatsAppWebLink(invalid, text)).toBe('');
  });
  it('encodes mailto values and rejects recipient or subject header injection', () => {
    const href = new URL(emailClientLink('self@example.test', 'Abrechnung & Termin', 'Zeile1\nBcc: keine neue Kopfzeile'));
    expect(href.searchParams.get('subject')).toBe('Abrechnung & Termin');
    expect(href.searchParams.get('body')).toBe('Zeile1\nBcc: keine neue Kopfzeile');
    expect(emailClientLink('self@example.test\r\nBcc:other@example.test', 'Test', '')).toBe('');
    expect(emailClientLink('self@example.test', 'Test\r\nBcc:other@example.test', '')).toBe('');
  });
  it('provides a manual browser link and never calls any send endpoint', () => {
    wrap(<QuickMessageComposer phone="0170 1234567" subject="Frist" message="Bitte Termin prüfen" onClose={vi.fn()} />);
    const chat = screen.getByRole('link', { name: 'WhatsApp-Chat mit Text öffnen' });
    expect(new URL(chat.href).searchParams.get('phone')).toBe('491701234567');
    expect(chat).toHaveAttribute('target', '_blank'); expect(chat).toHaveAttribute('rel', 'noopener noreferrer');
    expect(screen.getByRole('link', { name: 'WhatsApp Web öffnen / anmelden' })).toHaveAttribute('href', 'https://web.whatsapp.com/');
    expect(api.post).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('Nachrichtenweg'), { target: { value: 'email_draft' } });
    fireEvent.change(screen.getByLabelText('E-Mail-Adresse'), { target: { value: 'self@example.test' } });
    expect(screen.getByRole('link', { name: 'E-Mail-Entwurf öffnen' }).href).toMatch(/^mailto:/);
  });
  it('clears recipient and text on account change before any external draft can open', () => {
    wrap(<QuickMessageComposer phone="01701234567" recipientName="Private Person" message="Private Nachricht" onClose={vi.fn()} />);
    act(() => window.dispatchEvent(new Event('workspace-owner')));
    expect(screen.getByRole('alert')).toHaveTextContent('Sitzung wurde geändert');
    expect(screen.queryByText(/Private Person/)).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'WhatsApp-Chat mit Text öffnen' })).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue('Private Nachricht')).not.toBeInTheDocument();
  });
});

describe('durable personal reminder UI', () => {
  it('catches a synchronous capture failure after its logout listeners are registered and performs no read', async () => {
    const removed = vi.spyOn(window, 'removeEventListener');
    api.captureSession.mockImplementation(() => {
      window.dispatchEvent(new Event('workspace-logout'));
      throw Object.assign(new Error('Die Sitzung wurde geändert.'), { code: 'SESSION_CHANGED' });
    });
    const { result, unmount } = renderHook(() => useReminders());
    await waitFor(() => expect(result.current.error).toMatch(/Sitzung wurde geändert/));
    expect(result.current.page).toBeNull(); expect(api.get).not.toHaveBeenCalled();
    unmount();
    expect(removed).toHaveBeenCalledWith('workspace-logout', expect.any(Function));
    expect(removed).toHaveBeenCalledWith('workspace-owner', expect.any(Function));
    removed.mockRestore();
  });
  it('uses Berlin calendar dates even when the UTC date differs', () => {
    const now = new Date('2026-11-06T23:30:00Z');
    expect(berlinLocal(now)).toBe('2026-11-07T00:30');
    expect(reminderDefault(null, 7, '09:00', now)).toBe('2026-11-08T09:00');
    expect(reminderDefault('2026-12-01', 7, '09:00', now)).toBe('2026-11-24T09:00');
  });
  it('guards double clicks and reuses the same command after an unconfirmed response', async () => {
    let reject; api.post.mockImplementationOnce(() => new Promise((_, no) => { reject = no; }));
    wrap(<ReminderPlanner sourceKind="task" sourceId="task-a" sourceTitle="Abrechnung prüfen" onClose={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('Datum und Uhrzeit (Europe/Berlin)'), { target: { value: '2026-12-01T09:00' } });
    const submit = screen.getByRole('button', { name: 'Erinnerung speichern' });
    fireEvent.click(submit); fireEvent.click(submit);
    expect(api.post).toHaveBeenCalledTimes(1);
    const original = api.post.mock.calls[0][1];
    expect(original).toMatchObject({ source_kind: 'task', source_id: 'task-a', channel: 'in_app', local_due_at: '2026-12-01T09:00' });
    await act(async () => reject(new Error('Antwort verloren')));
    expect(screen.getByRole('alert')).toHaveTextContent('Antwort verloren');
    api.post.mockResolvedValueOnce({ id: 'reminder-a', due_at: '2026-12-01T08:00:00+00:00' });
    fireEvent.click(screen.getByRole('button', { name: 'Erinnerung speichern' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Erinnerung gespeichert');
    expect(api.post.mock.calls[1][1]).toEqual(original);
    expect(api.post.mock.calls.every(([path]) => path === '/notifications/reminders')).toBe(true);
  });
  it('shows actual due reminders, linked source and manual draft without marking a task done', async () => {
    api.get.mockResolvedValue({ items: [{ id: 'r1', revision: 3, status: 'due', source: { title: 'Frist prüfen', href: '/tasks?focus_id=t1' },
      due_at: '2026-11-06T09:00:00Z', channel: 'whatsapp_web', recipient: '+491701234567', message: 'Erinnerung' }], total: 1, next_offset: null });
    api.post.mockResolvedValue({ status: 'done' });
    wrap(<ReminderArrival />);
    expect(await screen.findByRole('link', { name: 'Frist prüfen' })).toHaveAttribute('href', '/tasks?focus_id=t1');
    expect(screen.getByRole('link', { name: 'WhatsApp-Entwurf öffnen' }).href).toMatch(/^https:\/\/web\.whatsapp\.com\/send/);
    fireEvent.click(screen.getByRole('button', { name: 'Erinnerung erledigt' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(api.post.mock.calls[0]).toEqual(['/notifications/reminders/r1/command', expect.objectContaining({ action: 'done', base_revision: 3 })]);
  });
  it('does not display paused reminders or stale source data after a session switch', async () => {
    api.get.mockResolvedValue({ items: [{ id: 'r1', status: 'due', delivery_paused: true, source: { title: 'Ruhezeit', href: '/tasks?focus_id=t1' } }], total: 1 });
    wrap(<ReminderArrival />);
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    act(() => window.dispatchEvent(new Event('workspace-logout')));
    expect(screen.queryByText('Ruhezeit')).not.toBeInTheDocument();
  });
  it('preserves the entire saved reminder text when adding its source would exceed the draft limit', () => {
    const text = 'ü'.repeat(2000);
    wrap(<ReminderDraftLink row={{ channel: 'whatsapp_web', recipient: '+491701234567', message: text, source: { title: 'Frist', href: '/tasks?focus_id=t1' } }} />);
    const href = new URL(screen.getByRole('link', { name: 'WhatsApp-Entwurf öffnen' }).href);
    expect(href.searchParams.get('text')).toBe(text);
  });
  it('does not revive a confirmed plan or callback after the account changed while saving', async () => {
    let resolve; api.post.mockImplementationOnce(() => new Promise(yes => { resolve = yes; })); const onSaved = vi.fn();
    wrap(<ReminderPlanner sourceKind="task" sourceId="task-a" sourceTitle="Private Quelle" onSaved={onSaved} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Erinnerung speichern' }));
    act(() => window.dispatchEvent(new Event('workspace-owner')));
    await act(async () => resolve({ id: 'old-plan', due_at: '2026-12-01T08:00:00Z' }));
    expect(onSaved).not.toHaveBeenCalled();
    expect(screen.queryByText('Private Quelle')).not.toBeInTheDocument();
    expect(screen.queryByText(/Erinnerung gespeichert/)).not.toBeInTheDocument();
  });
  it('reports a failed personal reminder command in the widget and preserves the due source', async () => {
    api.get.mockResolvedValue({ items: [{ id: 'r1', revision: 1, status: 'due', due_at: '2026-11-06T09:00:00Z', source: { title: 'Frist prüfen', href: '/tasks?focus_id=t1' } }], total: 1 });
    api.post.mockRejectedValue(new Error('Änderung wurde nicht bestätigt'));
    wrap(<ReminderArrival />);
    fireEvent.click(await screen.findByRole('button', { name: 'Erinnerung erledigt' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Änderung wurde nicht bestätigt');
    expect(screen.getByRole('link', { name: 'Frist prüfen' })).toBeInTheDocument();
  });
});
