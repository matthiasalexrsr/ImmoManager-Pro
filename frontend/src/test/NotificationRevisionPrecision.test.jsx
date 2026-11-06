import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import NotificationArrival from '../components/NotificationArrival';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn(), captureSession: () => () => {} } }));
const row = { id: 'task', updated_at: '2026-11-06T08:00:00.123456Z', title: 'Zuordnung prüfen' };
beforeEach(() => { vi.resetAllMocks(); sessionStorage.clear(); api.post.mockResolvedValue({}); });
afterEach(cleanup);
function mount(revision) {
  api.get.mockResolvedValue({ notice: { revision: 0 }, source: { kind: 'task', entity_id: row.id,
    href: '/tasks?focus_id=task', revision, values: row } });
  return render(<MemoryRouter initialEntries={['/tasks?focus_id=task&notice_id=notice']}><NotificationArrival record={row} /></MemoryRouter>);
}
it('leaves a changed source unread when its database revision differs within the same millisecond', async () => {
  mount('2026-11-06T08:00:00.123457Z');
  expect(await screen.findByRole('alert')).toHaveTextContent('Die angezeigte Quelle wurde geändert.');
  expect(api.post).not.toHaveBeenCalled();
});
it('accepts an equivalent full-precision revision with a different UTC spelling and trailing zeros', async () => {
  mount('2026-11-06T08:00:00.123456000+00:00');
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/notifications/notice/receipt', expect.objectContaining({ source_revision: '2026-11-06T08:00:00.123456000+00:00' })));
});
