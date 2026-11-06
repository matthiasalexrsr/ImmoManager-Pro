import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useNavigate } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import Messages from '../pages/Messages';
import { api } from '../api';

vi.mock('../api', () => ({ api: { list: vi.fn(), get: vi.fn(), post: vi.fn(), captureSession: vi.fn(() => () => {}) } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: () => undefined }) }));
vi.mock('../contexts/DataStoreContext', () => ({ useEntities: () => ({ items: [] }) }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'reader', role: 'readonly' } }), useCanWrite: () => false }));
vi.mock('../components/NotificationInbox', () => ({ default: () => null }));
vi.mock('../features/channels/ChannelPanel', () => ({ default: () => null }));
vi.mock('../features/communication/CommunicationCenter', () => ({ default: () => null }));
const thread = { id: 'thread-a', subject: 'Abrechnung Stuttgart', message_count: 2 };
const message = id => ({ id, thread_id: thread.id, sender_name: 'Verwaltung', body: `Nachricht ${id}`, sent_at: '2026-11-06T09:00:00Z' });
const href = id => `/messages?focus_id=thread-a&source_id=${id}`;
let children;
beforeEach(() => {
  vi.clearAllMocks(); sessionStorage.clear(); localStorage.clear(); children = {}; api.captureSession.mockReturnValue(() => {});
  api.list.mockImplementation(path => Promise.resolve(path === '/messages/threads' ? [thread] : []));
  api.post.mockResolvedValue({});
  api.get.mockImplementation(path => {
    if (path === '/messages/threads/thread-a') return Promise.resolve(thread);
    if (path.includes('/page?')) return Promise.resolve({ items: [], next_cursor: null, thread });
    if (path.includes('/messages/threads/thread-a/messages/')) {
      const id = path.split('/').at(-1);
      return children[id] || Promise.resolve(message(id));
    }
    if (path === '/notifications/notice/source') return Promise.resolve({ notice: { revision: 0 }, source: {
      kind: 'message', entity_id: 'one', href: href('one'), title: 'Nachricht one', revision: message('one').sent_at, values: message('one'),
    } });
    return Promise.reject(new Error(`Unerwarteter Testaufruf ${path}`));
  });
});
afterEach(() => cleanup());
function View() {
  const navigate = useNavigate();
  return <><button onClick={() => navigate(href('two'))}>Zweite Nachricht</button><button onClick={() => navigate(-1)}>Zurück</button><button onClick={() => navigate(1)}>Vorwärts</button><Messages /></>;
}
const open = (route = href('one')) => render(<MemoryRouter initialEntries={[route]}><View /></MemoryRouter>);

it('catches synchronous session failure in contacts, thread list and focused message readers before any request', async () => {
  api.captureSession.mockImplementation(() => {
    window.dispatchEvent(new Event('workspace-logout'));
    throw Object.assign(new Error('Die Sitzung wurde geändert.'), { code: 'SESSION_CHANGED' });
  });
  open();
  expect(await screen.findByRole('alert')).toHaveTextContent('Sitzung wurde geändert');
  expect(api.captureSession).toHaveBeenCalledTimes(3);
  expect(api.list).not.toHaveBeenCalled(); expect(api.get).not.toHaveBeenCalled(); expect(api.post).not.toHaveBeenCalled();
  expect(screen.queryByText('Nachricht one')).not.toBeInTheDocument();
});

it('opens the exact message from a history or favorite link without an unrelated notice', async () => {
  open();
  expect(await screen.findByRole('region', { name: 'Ausgewählte Nachricht' })).toHaveTextContent('Nachricht one');
  expect(api.get).toHaveBeenCalledWith('/messages/threads/thread-a/messages/one', expect.objectContaining({ signal: expect.any(AbortSignal) }));
  expect(api.post).not.toHaveBeenCalled();
});

it('changes the selected message through committed navigation, Back and Forward', async () => {
  open(); await screen.findByText('Nachricht one');
  fireEvent.click(screen.getByRole('button', { name: 'Zweite Nachricht' }));
  expect(await screen.findByText('Nachricht two')).toBeInTheDocument();
  expect(screen.queryByText('Nachricht one')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Zurück' }));
  expect(await screen.findByText('Nachricht one')).toBeInTheDocument();
  expect(screen.queryByText('Nachricht two')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Vorwärts' }));
  expect(await screen.findByText('Nachricht two')).toBeInTheDocument();
});

it('rejects an absent child and a child from another thread without displaying or acknowledging it', async () => {
  children.one = Promise.resolve({ ...message('one'), thread_id: 'foreign', body: 'Fremder Inhalt' });
  open(href('one') + '&notice_id=notice');
  expect(await screen.findByRole('alert')).toHaveTextContent('gehört nicht zu dieser Konversation');
  expect(screen.queryByText('Fremder Inhalt')).not.toBeInTheDocument();
  expect(api.post).not.toHaveBeenCalled();
  children.two = Promise.reject(new Error('Nachricht gelöscht oder nicht zugänglich'));
  fireEvent.click(screen.getByRole('button', { name: 'Zweite Nachricht' }));
  expect(await screen.findByText(/Nachricht gelöscht oder nicht zugänglich/)).toBeInTheDocument();
  expect(screen.queryByRole('region', { name: 'Ausgewählte Nachricht' })).not.toBeInTheDocument();
});

it('ignores a late child response after navigation and after a session change', async () => {
  let resolve; children.one = new Promise(yes => { resolve = yes; }); open();
  await waitFor(() => expect(api.get.mock.calls.some(([path]) => path.endsWith('/messages/one'))).toBe(true));
  fireEvent.click(screen.getByRole('button', { name: 'Zweite Nachricht' }));
  await screen.findByText('Nachricht two');
  await act(async () => resolve({ ...message('one'), body: 'Veralteter Inhalt' }));
  expect(screen.queryByText('Veralteter Inhalt')).not.toBeInTheDocument();
  act(() => window.dispatchEvent(new Event('workspace-logout')));
  expect(screen.queryByText('Nachricht two')).not.toBeInTheDocument();
});

it('acknowledges only a notice whose own child and conversation have actually loaded', async () => {
  open(href('one') + '&notice_id=notice');
  await screen.findByText('Nachricht one');
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/notifications/notice/receipt', expect.objectContaining({ source_kind: 'message', source_id: 'one' })));
  expect(api.post).toHaveBeenCalledTimes(1);
});
