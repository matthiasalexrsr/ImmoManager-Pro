import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter, useNavigate } from 'react-router-dom';
import NotificationArrival from '../components/NotificationArrival';
import { api } from '../api';
vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn(), captureSession: () => () => {} } }));
const row = { id: 'task', updated_at: '2026-11-06T08:00:00Z', title: 'Abrechnung prüfen' };
beforeEach(() => {
  vi.resetAllMocks(); sessionStorage.clear();
  api.get.mockResolvedValue({ notice: { revision: 0 }, source: { kind: 'task', entity_id: 'task', href: '/tasks?focus_id=task', revision: row.updated_at, values: row } });
  api.post.mockResolvedValue({});
});
afterEach(() => { cleanup(); window.history.replaceState({}, '', '/'); });
it('acknowledges the committed route rather than a temporarily attempted browser Back destination', async () => {
  window.history.replaceState({}, '', '/tasks?focus_id=task&notice_id=attempted');
  render(<MemoryRouter initialEntries={['/tasks?focus_id=task&notice_id=displayed']}><NotificationArrival record={row} /></MemoryRouter>);
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/notifications/displayed/receipt', expect.objectContaining({ source_id: 'task' })));
  expect(api.get).not.toHaveBeenCalledWith('/notifications/attempted/source');
  expect(api.post).not.toHaveBeenCalledWith('/notifications/attempted/receipt', expect.anything());
});
it('reacts to a different committed notice for the same source without a global-location dependency', async () => {
  function View() { const navigate = useNavigate(); return <><button onClick={() => navigate('/tasks?focus_id=task&notice_id=next')}>Nächsten Hinweis öffnen</button><NotificationArrival record={row} /></>; }
  render(<MemoryRouter initialEntries={['/tasks?focus_id=task&notice_id=first']}><View /></MemoryRouter>);
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/notifications/first/receipt', expect.anything()));
  fireEvent.click(screen.getByRole('button', { name: 'Nächsten Hinweis öffnen' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/notifications/next/receipt', expect.anything()));
});
it('leaves an unrelated parent or unloaded source unread', async () => {
  render(<MemoryRouter initialEntries={['/tasks?focus_id=another&notice_id=notice']}><NotificationArrival record={row} /></MemoryRouter>);
  await new Promise(resolve => setTimeout(resolve, 10));
  expect(api.get).not.toHaveBeenCalled(); expect(api.post).not.toHaveBeenCalled();
});
it('does not create another receipt when an already archived source is opened again', async () => {
  api.get.mockResolvedValue({ notice: { revision: 1, status: 'archived' }, source: { kind: 'task', entity_id: 'task',
    href: '/tasks?focus_id=task', revision: row.updated_at, values: row } });
  render(<MemoryRouter initialEntries={['/tasks?focus_id=task&notice_id=archived']}><NotificationArrival record={row} /></MemoryRouter>);
  expect(await screen.findByText('Hinweis persönlich gelesen und archiviert.')).toBeVisible();
  expect(api.post).not.toHaveBeenCalled();
});

it('keeps a synchronous session capture failure within the receipt error state and can retry', async () => {
  const capture = vi.spyOn(api, 'captureSession').mockImplementationOnce(() => { throw Object.assign(new Error('Sitzung geändert'), { code: 'SESSION_CHANGED' }); });
  try {
    render(<MemoryRouter initialEntries={['/tasks?focus_id=task&notice_id=notice']}><NotificationArrival record={row} /></MemoryRouter>);
    expect(await screen.findByRole('alert')).toHaveTextContent('Sitzung geändert');
    expect(api.get).not.toHaveBeenCalled(); expect(api.post).not.toHaveBeenCalled();
    capture.mockRestore();
    fireEvent.click(screen.getByRole('button', { name: 'Erneut bestätigen' }));
    expect(await screen.findByText('Hinweis persönlich gelesen und archiviert.')).toBeVisible();
  } finally { capture.mockRestore(); }
});
