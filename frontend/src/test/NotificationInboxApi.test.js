import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('../api', () => ({ api: apiMock }));

import { notificationInboxService } from '../features/notificationInbox/notificationInboxApi';

const authority = {
  id: 'user-1',
  role: 'readonly',
  is_active: true,
  portfolio_access: 'selected',
  portfolio_access_origin: 'explicit',
  portfolio_ids: ['portfolio-1'],
  write_permissions: [],
};
const inboxItem = {
  id: 'n1',
  notification_type: 'task_due',
  title: 'Aufgabe fällig',
  content: 'Bitte prüfen',
  severity: 'warning',
  entity_type: 'task',
  entity_id: 'task-1',
  created_at: '2026-10-03T18:00:00+00:00',
  read_at: null,
  actions: { mark_read: true },
};
const page = {
  items: [inboxItem],
  full_count: 17,
  unread_count: 17,
  has_more: true,
  next_cursor: 'opaque-next',
  consistency: 'live',
  snapshot_token: null,
  actions: { mark_all_read: false },
};

describe('notification inbox Phase A API contract', () => {
  beforeEach(() => vi.clearAllMocks());

  it('uses fresh /auth/me and only the exact bounded Phase A query', async () => {
    apiMock.get.mockResolvedValueOnce(authority).mockResolvedValueOnce(page);

    await expect(notificationInboxService.loadAuthority()).resolves.toEqual(authority);
    await expect(notificationInboxService.listInbox({
      status: 'unread',
      after: 'opaque-current',
      limit: 10,
    })).resolves.toMatchObject({ unread_count: 17, consistency: 'live' });

    expect(apiMock.get).toHaveBeenNthCalledWith(1, '/auth/me', { signal: undefined });
    expect(apiMock.get).toHaveBeenNthCalledWith(
      2,
      '/notifications/inbox?status=unread&after=opaque-current&limit=10',
      { signal: undefined },
    );
  });

  it('rejects inactive fresh authority', async () => {
    apiMock.get.mockResolvedValue({ ...authority, is_active: false });
    await expect(notificationInboxService.loadAuthority())
      .rejects.toThrow('invalid_notification_authority');
  });

  it('uses the personal read endpoint and validates the Phase A read receipt', async () => {
    apiMock.post.mockResolvedValue({
      notification_id: 'n1',
      read_at: '2026-10-03T18:10:00.123456+00:00',
    });
    await expect(notificationInboxService.markRead('n1')).resolves.toEqual({
      notification_id: 'n1',
      read_at: '2026-10-03T18:10:00.123456+00:00',
    });
    expect(apiMock.post).toHaveBeenCalledWith(
      '/notifications/inbox/n1/read',
      {},
      { signal: undefined },
    );
  });
});
