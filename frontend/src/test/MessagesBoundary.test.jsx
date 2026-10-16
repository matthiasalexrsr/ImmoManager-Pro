import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import Messages from '../pages/Messages';
import { api } from '../api';

vi.mock('../api', () => ({ api: { list: vi.fn(), get: vi.fn(), post: vi.fn(), patch: vi.fn(), captureSession: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: () => undefined }) }));
vi.mock('../contexts/DataStoreContext', () => ({ useEntities: () => ({ items: [] }) }));
vi.mock('../components/FormModal', () => ({ default: () => null }));
const threads = [{ id: 'a', subject: 'Vorgang A', message_count: 1 }, { id: 'b', subject: 'Vorgang B', message_count: 1 }];
const message = (id, body) => ({ id, thread_id: id, sender_name: 'Pruefung', body, sent_at: '2026-10-15T09:00:00Z' });
function deferred() { let resolve; let reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
let reads;
beforeEach(() => {
  vi.resetAllMocks(); reads = {};
  api.captureSession.mockReturnValue(() => {});
  api.list.mockImplementation(path => {
    if (path === '/messages/threads') return Promise.resolve(threads);
    if (path.includes('/messages/threads/')) return reads[path.split('/')[3]]?.promise || Promise.resolve([]);
    return Promise.resolve([]);
  });
  api.get.mockImplementation(path => {
    const id = path.split('/')[3];
    return (reads[id]?.promise || Promise.resolve([])).then(items => ({ items, next_cursor: null }));
  });
});
afterEach(() => cleanup());
async function open() { render(<MemoryRouter><Messages /></MemoryRouter>); fireEvent.click(await screen.findByRole('button', { name: /Konversationen/ })); }
const choose = id => fireEvent.click(screen.getByText(`Vorgang ${id.toUpperCase()}`, { selector: '.message-item-title' }));

it('never displays late A content under B even when transport ignores abort', async () => {
  reads.a = deferred(); reads.b = deferred(); await open(); choose('a'); choose('b');
  await act(async () => reads.b.resolve([message('b', 'B-INHALT')]));
  expect(screen.getByText('B-INHALT')).toBeInTheDocument();
  await act(async () => reads.a.resolve([message('a', 'A-INHALT')]));
  expect(screen.getByRole('heading', { name: 'Vorgang B' })).toBeInTheDocument();
  expect(screen.queryByText('A-INHALT')).not.toBeInTheDocument();
  expect(screen.getByText('B-INHALT')).toBeInTheDocument();
});

it('clears old content while the next conversation is loading', async () => {
  reads.a = deferred(); reads.b = deferred(); await open(); choose('a');
  await act(async () => reads.a.resolve([message('a', 'A-INHALT')])); choose('b');
  expect(screen.queryByText('A-INHALT')).not.toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent('Nachrichten werden geladen');
});

it('shows failed reads rather than presenting an empty successful thread', async () => {
  reads.a = deferred(); await open(); choose('a');
  await act(async () => reads.a.reject(new Error('Nachrichtenserver nicht erreichbar')));
  expect(await screen.findByRole('alert')).toHaveTextContent('Nachrichtenserver nicht erreichbar');
  expect(screen.queryByText(/Noch keine Nachrichten/)).not.toBeInTheDocument();
});

it('keeps separate drafts for A and B', async () => {
  await open(); choose('a');
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Entwurf A' } }); choose('b');
  expect(screen.getByRole('textbox')).toHaveValue('');
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Entwurf B' } }); choose('a');
  expect(screen.getByRole('textbox')).toHaveValue('Entwurf A'); choose('b');
  expect(screen.getByRole('textbox')).toHaveValue('Entwurf B');
});

it('a late send confirmation neither switches thread nor erases the other draft', async () => {
  const send = deferred(); api.post.mockReturnValue(send.promise);
  await open(); choose('a');
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Nachricht A' } });
  fireEvent.click(screen.getByRole('button', { name: 'Senden' })); choose('b');
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Entwurf B bleibt' } });
  await act(async () => send.resolve(message('a', 'Nachricht A')));
  expect(screen.getByRole('heading', { name: 'Vorgang B' })).toBeInTheDocument();
  expect(screen.getByRole('textbox')).toHaveValue('Entwurf B bleibt');
  expect(api.post.mock.calls[0][0]).toBe('/messages/threads/a/messages');
  expect(api.post.mock.calls[0][1].thread_id).toBe('a');
});

it('prevents duplicate sends while keeping a failed draft editable', async () => {
  const send = deferred(); api.post.mockReturnValue(send.promise);
  await open(); choose('a');
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Nicht verlieren' } });
  fireEvent.click(screen.getByRole('button', { name: 'Senden' }));
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter', ctrlKey: true });
  expect(api.post).toHaveBeenCalledTimes(1);
  await act(async () => send.reject(new Error('Speicherung nicht bestaetigt')));
  expect(screen.getByRole('textbox')).toHaveValue('Nicht verlieren');
  expect(await screen.findByRole('alert')).toHaveTextContent('Speicherung nicht bestaetigt');
});


it('aborts the previous read and ignores its late failure after selecting B', async () => {
  reads.a = deferred(); reads.b = deferred(); await open(); choose('a');
  await waitFor(() => expect(api.get.mock.calls.some(([url]) => url.startsWith('/messages/threads/a/page?'))).toBe(true));
  const firstSignal = api.get.mock.calls.find(([url]) => url.startsWith('/messages/threads/a/page?'))[1].signal;
  choose('b'); expect(firstSignal.aborted).toBe(true);
  await act(async () => reads.b.resolve([message('b', 'B bleibt sichtbar')]));
  await act(async () => reads.a.reject(new Error('Alter A-Fehler')));
  expect(screen.getByText('B bleibt sichtbar')).toBeInTheDocument();
  expect(screen.queryByText('Alter A-Fehler')).not.toBeInTheDocument();
});

it('keeps a new same-thread draft when an older send is confirmed', async () => {
  const sending = deferred(); api.post.mockReturnValue(sending.promise);
  await open(); choose('a');
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Gesendeter Text' } });
  fireEvent.click(screen.getByRole('button', { name: 'Senden' }));
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Neue Antwort' } });
  await act(async () => sending.resolve(message('a', 'Gesendeter Text')));
  expect(screen.getByRole('textbox')).toHaveValue('Neue Antwort');
});

it('does not erase text retyped to the same bytes while a send was pending', async () => {
  const sending = deferred(); api.post.mockReturnValue(sending.promise);
  await open(); choose('a');
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Text' } });
  fireEvent.click(screen.getByRole('button', { name: 'Senden' }));
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Anderer Text' } });
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Text' } });
  await act(async () => sending.resolve(message('a', 'Text')));
  expect(screen.getByRole('textbox')).toHaveValue('Text');
});

it('reconciles an uncertain send with its exact original key and preserves later edits', async () => {
  api.post.mockRejectedValueOnce(new Error('Verbindung nach möglicher Speicherung unterbrochen'))
    .mockResolvedValueOnce(message('a', 'Ursprünglicher Text'));
  await open(); choose('a');
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Ursprünglicher Text' } });
  fireEvent.click(screen.getByRole('button', { name: 'Senden' }));
  await screen.findByRole('button', { name: 'Speicherung abgleichen' });
  const original = api.post.mock.calls[0][1];
  expect(original.idempotency_key).toBeTruthy();
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Danach geschrieben' } });
  expect(screen.getByRole('button', { name: 'Senden' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Speicherung abgleichen' }));
  await act(async () => {});
  expect(api.post.mock.calls[1][1]).toEqual(original);
  expect(screen.getByRole('textbox')).toHaveValue('Danach geschrieben');
});

it('keeps cursor pages bounded and can return to the exact newer page', async () => {
  api.get.mockImplementation(url => url.includes('cursor=older-a')
    ? Promise.resolve({ items: [message('a', 'Älteste Seite')], next_cursor: null, total: 101 })
    : Promise.resolve({ items: [message('a', 'Neueste Seite')], next_cursor: 'older-a', total: 101 }));
  await open(); choose('a'); await screen.findByText('Neueste Seite');
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Bleibender Entwurf' } });
  fireEvent.click(screen.getByRole('button', { name: 'Ältere Nachrichten' }));
  expect(await screen.findByText('Älteste Seite')).toBeInTheDocument();
  expect(screen.queryByText('Neueste Seite')).not.toBeInTheDocument();
  const pageCalls = api.get.mock.calls.filter(([url]) => url.startsWith('/messages/threads/a/page?'));
  expect(pageCalls[1][0]).toContain('cursor=older-a');
  expect(screen.getByRole('textbox')).toHaveValue('Bleibender Entwurf');
  fireEvent.click(screen.getByRole('button', { name: 'Neuere Nachrichten' }));
  expect(await screen.findByText('Neueste Seite')).toBeInTheDocument();
  expect(screen.queryByText('Älteste Seite')).not.toBeInTheDocument();
  const finalPageCalls = api.get.mock.calls.filter(([url]) => url.startsWith('/messages/threads/a/page?'));
  expect(finalPageCalls[2][0]).not.toContain('cursor=');
});

it('retries a failed older page without pretending the thread is empty', async () => {
  let olderAttempts = 0;
  api.get.mockImplementation(url => {
    if (!url.includes('cursor=continue-a')) return Promise.resolve({
      items: [message('a', 'Aktuell')], next_cursor: 'continue-a',
    });
    olderAttempts += 1;
    if (olderAttempts === 1) return Promise.reject(new Error('Seitenausfall'));
    return Promise.resolve({ items: [message('a', 'Älterer Inhalt')], next_cursor: null });
  });
  await open(); choose('a'); await screen.findByText('Aktuell');
  fireEvent.click(screen.getByRole('button', { name: 'Ältere Nachrichten' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Seitenausfall');
  expect(screen.queryByText(/Noch keine Nachrichten/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Nachrichten erneut laden' }));
  expect(await screen.findByText('Älterer Inhalt')).toBeInTheDocument();
  const pageCalls = api.get.mock.calls.filter(([url]) => url.startsWith('/messages/threads/a/page?'));
  expect(pageCalls[1][0]).toBe(pageCalls[2][0]);
});

it('refuses cross-thread rows even if a transport returns success', async () => {
  reads.a = deferred(); await open(); choose('a');
  await act(async () => reads.a.resolve([message('b', 'Fremder Inhalt')]));
  expect(await screen.findByRole('alert')).toHaveTextContent('gehört nicht zu dieser Konversation');
  expect(screen.queryByText('Fremder Inhalt')).not.toBeInTheDocument();
});

it('invalidates a pending read and draft on session change', async () => {
  reads.a = deferred(); await open(); choose('a');
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Privater Entwurf' } });
  act(() => window.dispatchEvent(new Event('workspace-logout')));
  await act(async () => reads.a.resolve([message('a', 'Private späte Antwort')]));
  expect(screen.queryByText('Private späte Antwort')).not.toBeInTheDocument();
  expect(screen.queryByDisplayValue('Privater Entwurf')).not.toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: 'Vorgang A' })).not.toBeInTheDocument();
});

it('ignores a send completion after a session change', async () => {
  const sending = deferred(); api.post.mockReturnValue(sending.promise);
  await open(); choose('a');
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Private Nachricht' } });
  fireEvent.click(screen.getByRole('button', { name: 'Senden' }));
  act(() => window.dispatchEvent(new Event('workspace-logout')));
  const calls = api.get.mock.calls.length;
  await act(async () => sending.resolve(message('a', 'Private Nachricht')));
  expect(api.get).toHaveBeenCalledTimes(calls);
  expect(screen.queryByRole('heading', { name: 'Vorgang A' })).not.toBeInTheDocument();
});
