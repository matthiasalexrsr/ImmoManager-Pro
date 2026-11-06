import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, useNavigate } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import NotificationInbox from '../components/NotificationInbox';
import { api } from '../api';

const actor = vi.hoisted(() => ({ id: 'reader-a' }));
vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn(), captureSession: vi.fn(() => () => {}) } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: actor.id, role: 'readonly' } }), useCanWrite: () => false }));
vi.mock('../components/NotificationEmailPreview', () => ({ default: () => null }));
const selected = id => ({ id, revision: 0, title: `Hinweis ${id}`, content: `Vollständiger Inhalt ${id}`, status: 'unread',
  created_at: '2026-11-06T08:00:00Z', updated_at: '2026-11-06T08:00:00Z', severity: 'info', email_eligible: false,
  target: { title: 'Abrechnung prüfen', kind: 'task', entity_id: 'task', href: '/tasks?focus_id=task' }, open_href: `/tasks?focus_id=task&notice_id=${id}` });
const page = { items: Array.from({ length: 50 }, (_, index) => selected(`list-${index}`)), total: 51, unread_count: 51, snapshot: 'current', next_cursor: 'next' };
let single;
beforeEach(() => {
  vi.clearAllMocks(); sessionStorage.clear(); actor.id = 'reader-a'; single = {}; api.captureSession.mockReturnValue(() => {});
  api.post.mockResolvedValue({});
  api.get.mockImplementation(path => {
    if (path.startsWith('/notifications/inbox?')) return Promise.resolve(page);
    if (path.endsWith('/outer/source')) return Promise.resolve({ notice: { revision: 0, status: 'unread' }, source: {
      kind: 'notification', entity_id: 'outside', href: '/notifications?focus_id=outside', title: 'Hinweis outside', revision: selected('outside').updated_at, values: selected('outside'),
    } });
    const id = path.split('/').at(-1);
    return single[id] || Promise.resolve(selected(id));
  });
});
afterEach(cleanup);
const route = id => `/notifications?focus_id=${id}&status=unread&severity=critical&kind=task`;
function View() {
  const navigate = useNavigate();
  return <><button onClick={() => navigate(route('second'))}>Anderen Hinweis</button><button onClick={() => navigate(-1)}>Vorheriger Hinweis</button><button onClick={() => navigate(1)}>Nächster Hinweis</button><NotificationInbox /></>;
}
const content = (href = route('outside')) => <MemoryRouter initialEntries={[href]}><View /></MemoryRouter>;

it('handles synchronous capture failure in both inbox and detail after registering cleanup listeners', async () => {
  api.captureSession.mockImplementation(() => {
    window.dispatchEvent(new Event('workspace-logout'));
    throw Object.assign(new Error('Die Sitzung wurde geändert.'), { code: 'SESSION_CHANGED' });
  });
  render(content());
  const detail = screen.getByRole('region', { name: 'Ausgewählter Hinweis' });
  expect(await within(detail).findByRole('alert')).toHaveTextContent('Sitzung wurde geändert');
  expect(api.captureSession).toHaveBeenCalledTimes(2);
  expect(api.get).not.toHaveBeenCalled(); expect(api.post).not.toHaveBeenCalled();
  expect(screen.queryByText('Vollständiger Inhalt outside')).not.toBeInTheDocument();
});

it('loads notice 51 separately from a bounded filtered page without archiving it', async () => {
  render(content());
  const detail = await screen.findByRole('region', { name: 'Ausgewählter Hinweis' });
  expect(await within(detail).findByText('Vollständiger Inhalt outside')).toBeInTheDocument();
  expect(within(detail).getByRole('link', { name: 'Hinweis outside' })).toHaveAttribute('href', '/tasks?focus_id=task&notice_id=outside');
  expect(api.get).toHaveBeenCalledWith('/notifications/outside', expect.objectContaining({ signal: expect.any(AbortSignal) }));
  expect(screen.getByLabelText('Ansicht')).toHaveValue('unread'); expect(screen.getByLabelText('Dringlichkeit')).toHaveValue('critical');
  expect(api.get.mock.calls.some(([path]) => path.includes('cursor=next'))).toBe(false);
  expect(api.post).not.toHaveBeenCalled();
});

it('shows an archived personal notice even when the current unread list is empty', async () => {
  single.outside = Promise.resolve({ ...selected('outside'), status: 'archived', revision: 3, read_at: '2026-11-06T10:00:00Z', archived_at: '2026-11-06T10:00:00Z' });
  api.get.mockImplementation(path => path.startsWith('/notifications/inbox?') ? Promise.resolve({ ...page, items: [], total: 0 }) : single.outside);
  render(content());
  expect(await screen.findByRole('button', { name: 'Wieder in den Eingang' })).toBeInTheDocument();
  expect(screen.getByText('Vollständiger Inhalt outside')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Wieder in den Eingang' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/notifications/outside/receipt', expect.objectContaining({ action: 'reopen', base_revision: 3 })));
});

it.each([403, 404])('shows a clear %i failure, never acknowledges missing details, and retries', async code => {
  single.outside = Promise.reject(Object.assign(new Error('Refused'), { statusCode: code }));
  render(content(route('outside') + '&notice_id=outer'));
  expect(await screen.findByRole('alert')).toHaveTextContent(code === 403 ? 'fehlt die aktuelle Berechtigung' : 'gelöscht oder ist nicht zugänglich');
  expect(api.post).not.toHaveBeenCalled();
  single.outside = Promise.resolve(selected('outside'));
  fireEvent.click(screen.getByRole('button', { name: 'Hinweis erneut laden' }));
  expect(await screen.findByText('Vollständiger Inhalt outside')).toBeInTheDocument();
});

it('follows Back and Forward without reusing the previous focused record', async () => {
  render(content()); await screen.findByText('Vollständiger Inhalt outside');
  fireEvent.click(screen.getByRole('button', { name: 'Anderen Hinweis' }));
  await screen.findByText('Vollständiger Inhalt second'); expect(screen.queryByText('Vollständiger Inhalt outside')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Vorheriger Hinweis' }));
  await screen.findByText('Vollständiger Inhalt outside'); expect(screen.queryByText('Vollständiger Inhalt second')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Nächster Hinweis' }));
  await screen.findByText('Vollständiger Inhalt second');
});

it('fences a late old-owner response and never exposes that owners personal receipt', async () => {
  let resolve; single.outside = new Promise(yes => { resolve = yes; }); const view = render(content());
  await waitFor(() => expect(api.get.mock.calls.some(([path]) => path === '/notifications/outside')).toBe(true));
  single.outside = Promise.resolve({ ...selected('outside'), content: 'Neuer persönlicher Stand', revision: 0 });
  act(() => { actor.id = 'reader-b'; window.dispatchEvent(new Event('workspace-owner')); });
  view.rerender(content());
  await screen.findByText('Neuer persönlicher Stand');
  await act(async () => resolve({ ...selected('outside'), content: 'Alter privater Stand', archived_at: '2026-11-06T10:00:00Z', read_at: '2026-11-06T10:00:00Z', revision: 7 }));
  expect(screen.queryByText('Alter privater Stand')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Wieder in den Eingang' })).not.toBeInTheDocument();
});

it('acknowledges only after the exact focused notice is actually displayed', async () => {
  let resolve; single.outside = new Promise(yes => { resolve = yes; }); render(content(route('outside') + '&notice_id=outer'));
  await waitFor(() => expect(api.get.mock.calls.some(([path]) => path === '/notifications/outside')).toBe(true));
  expect(api.post).not.toHaveBeenCalled();
  single.outside = Promise.resolve(selected('outside'));
  await act(async () => resolve(selected('outside')));
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/notifications/outer/receipt', expect.objectContaining({ source_kind: 'notification', source_id: 'outside' })));
  await act(async () => {});
  expect(api.post).toHaveBeenCalledTimes(1);
});
