import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import NotificationArrival from '../components/NotificationArrival';
import NotificationBell from '../components/NotificationBell';
import NotificationInbox from '../components/NotificationInbox';
import { defaultDueDate } from '../utils/settingDefaults';
import { formatDate, formatDateTime, formatMoney, setDateFormat, setFormatLocale } from '../utils/format';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn(), captureSession: vi.fn(() => () => {}) } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'reader-a' } }) }));
const revision = '2026-10-16T12:00:00.123456';
const source = { kind: 'task', entity_id: 'task-id', revision, title: 'Lange deutsche Kündigungsfristenüberschrift', href: '/tasks?focus_id=task-id', values: { title: 'Quelle', updated_at: revision } };
const response = { notice: { revision: 0 }, source };
beforeEach(() => {
  vi.clearAllMocks(); window.sessionStorage.clear(); window.history.replaceState({}, '', '/');
  api.get.mockResolvedValue(response); api.post.mockResolvedValue({ revision: 1 });
});
afterEach(() => { cleanup(); setDateFormat(null); setFormatLocale('de-DE'); });
it('uses explicit date format without relabeling source money or converting amounts', () => {
  setDateFormat('YYYY-MM-DD'); setFormatLocale('en-US');
  expect(formatDate('2026-02-03')).toBe('2026-02-03');
  expect(formatDateTime('2026-02-03T12:00:00')).toMatch(/^2026-02-03 /);
  setDateFormat('MM/DD/YYYY'); expect(formatDate('2026-02-03')).toBe('02/03/2026');
  expect(formatMoney('1234.50', { currency: 'CHF' })).toContain('1,234.50');
  expect(formatMoney('1234.50', { currency: 'CHF' })).toContain('CHF');
  expect(formatMoney('1234.50')).toContain('€');
});
it('prefills next due day including year rollover without editing existing dates', () => {
  expect(defaultDueDate(15, new Date(2026, 0, 10))).toBe('2026-01-15');
  expect(defaultDueDate(3, new Date(2026, 11, 31))).toBe('2027-01-03');
  expect(defaultDueDate(28, new Date(2028, 1, 28))).toBe('2028-02-28');
});
it('does not acknowledge loading, empty, unrelated or stale source views', async () => {
  window.history.replaceState({}, '', '/tasks?focus_id=task-id&notice_id=notice-id');
  const page = render(<NotificationArrival rows={[]} />);
  await act(async () => {}); expect(api.post).not.toHaveBeenCalled();
  page.rerender(<NotificationArrival rows={[{ id: 'other', updated_at: revision }]} />);
  await act(async () => {}); expect(api.post).not.toHaveBeenCalled();
  page.rerender(<NotificationArrival rows={[{ id: 'task-id', updated_at: '2020-01-01' }]} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('geändert');
  expect(api.post).not.toHaveBeenCalled();
});
it('acknowledges rendered authorized target and reuses command after a lost answer', async () => {
  window.history.replaceState({}, '', '/tasks?focus_id=task-id&notice_id=notice-id');
  api.post.mockRejectedValueOnce(new Error('Offline')).mockResolvedValue({ revision: 1 });
  render(<NotificationArrival rows={[{ id: 'task-id', updated_at: revision }]} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Offline');
  const first = api.post.mock.calls[0][1];
  expect(first).toEqual(expect.objectContaining({ source_id: 'task-id', source_kind: 'task', source_revision: revision, base_revision: 0 }));
  fireEvent.click(screen.getByRole('button', { name: 'Erneut bestätigen' }));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('archiviert'));
  expect(api.post.mock.calls[1][1]).toEqual(first);
});
it('failed authorization preserves item without acknowledgement', async () => {
  window.history.replaceState({}, '', '/tasks?focus_id=task-id&notice_id=notice-id');
  api.get.mockRejectedValue(new Error('Nicht zugänglich'));
  render(<NotificationArrival rows={[{ id: 'task-id', updated_at: revision }]} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Nicht zugänglich');
  expect(api.post).not.toHaveBeenCalled();
});
it('inbox provides native keyboard and new-tab links and complete server snapshot', async () => {
  const notice = { id: 'notice-id', title: 'Sehr langer deutscher Hinweis', content: 'Prüfen', target: { title: 'Quelle' }, open_href: '/tasks?focus_id=task-id&notice_id=notice-id' };
  api.get.mockResolvedValue({ items: [notice], total: 27, unread_count: 27, snapshot: 'complete-authorized-inbox' });
  render(<MemoryRouter><NotificationInbox compact /></MemoryRouter>);
  const link = await screen.findByRole('link', { name: notice.title });
  expect(link).toHaveAttribute('href', notice.open_href);
  expect(screen.getByRole('status')).toHaveTextContent('27 ungelesen');
  fireEvent.click(screen.getByRole('button', { name: 'Alle berechtigten Hinweise gelesen archivieren' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/notifications/all/receipt', expect.objectContaining({ action: 'read_all', snapshot: 'complete-authorized-inbox' })));
});

it('returns keyboard focus to the notification bell after Escape', async () => {
  api.get.mockResolvedValue({ items: [], total: 0, unread_count: 0, snapshot: 'empty' });
  render(<MemoryRouter><NotificationBell /></MemoryRouter>);
  const button = screen.getByRole('button', { name: 'Benachrichtigungen' });
  fireEvent.click(button);
  const link = await screen.findByRole('link', { name: 'Vollst\u00e4ndiger Eingang und Archiv' });
  link.focus(); expect(link).toHaveFocus();
  fireEvent.keyDown(link, { key: 'Escape' });
  expect(button).toHaveFocus();
  expect(screen.queryByRole('link', { name: 'Vollst\u00e4ndiger Eingang und Archiv' })).not.toBeInTheDocument();
});
