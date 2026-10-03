import { describe, expect, it } from 'vitest';
import {
  inboxUtcDate,
  notificationPrincipalKey,
  parseInboxUtcMicros,
  validateAuthorityUser,
  validateInboxPage,
  validateMarkReadResponse,
} from '../features/notificationInbox/notificationInboxModel';

const item = (id, overrides = {}) => ({
  id,
  notification_type: 'task_due',
  title: `Titel ${id}`,
  content: `Inhalt ${id}`,
  severity: 'warning',
  entity_type: 'task',
  entity_id: `task-${id}`,
  created_at: '2026-10-03T18:00:00+00:00',
  read_at: null,
  actions: { mark_read: true },
  ...overrides,
});

const livePage = (overrides = {}) => ({
  items: [item('1')],
  full_count: 1,
  unread_count: 1,
  has_more: false,
  next_cursor: null,
  consistency: 'live',
  snapshot_token: null,
  actions: { mark_all_read: false },
  ...overrides,
});

describe('notification inbox Phase A model', () => {
  it('accepts exact full count larger than bounded page without fake total', () => {
    const value = validateInboxPage(livePage({
      items: Array.from({ length: 10 }, (_, index) => item(String(20 - index), {
        created_at: `2026-10-03T18:00:${String(59 - index).padStart(2, '0')}+00:00`,
      })),
      full_count: 37,
      unread_count: 37,
      has_more: true,
      next_cursor: 'opaque-next',
    }));
    expect(value.items).toHaveLength(10);
    expect(value.full_count).toBe(37);
    expect(value.unread_count).toBe(37);
    expect(value.consistency).toBe('live');
    expect(value.snapshot_token).toBeNull();
    expect(value.actions.mark_all_read).toBe(false);
  });

  it('rejects fake totals, duplicate ids, read items and invented Phase B fields', () => {
    expect(() => validateInboxPage(livePage({
      items: [item('2'), item('1')],
      full_count: 1,
      unread_count: 1,
    }))).toThrow('invalid_notification_inbox_page');

    expect(() => validateInboxPage(livePage({
      items: [item('same'), item('same')],
      full_count: 2,
      unread_count: 2,
    }))).toThrow('invalid_notification_inbox_page');

    expect(() => validateInboxPage(livePage({
      items: [item('1', { read_at: '2026-10-03T18:10:00+00:00' })],
    }))).toThrow('invalid_notification_inbox_page');

    expect(() => validateInboxPage(livePage({ snapshot_token: 'not-phase-a' })))
      .toThrow('invalid_notification_inbox_page');
    expect(() => validateInboxPage(livePage({ actions: { mark_all_read: true } })))
      .toThrow('invalid_notification_inbox_page');
  });

  it('accepts live null created_at and preserves early years and plausible UTC offsets', () => {
    expect(validateInboxPage(livePage({
      items: [item('null-created', { created_at: null })],
    })).items[0].created_at).toBeNull();

    const early = inboxUtcDate('0099-01-02T03:04:05.123456Z');
    expect(early.getUTCFullYear()).toBe(99);
    expect(early.getUTCMonth()).toBe(0);
    expect(early.getUTCDate()).toBe(2);
    expect(parseInboxUtcMicros('2026-10-03T18:00:00+23:59')).toBeTypeOf('bigint');

    expect(() => parseInboxUtcMicros('2026-10-03T18:00:00+24:00'))
      .toThrow('invalid_notification_timestamp');
    expect(() => parseInboxUtcMicros('2026-10-03T18:00:00+05:60'))
      .toThrow('invalid_notification_timestamp');
  });

  it('rejects unstable descending order across a page boundary', () => {
    const previousLast = item('z', { created_at: '2026-10-03T18:00:10+00:00' });
    expect(() => validateInboxPage(livePage({
      items: [item('x', { created_at: '2026-10-03T18:00:11+00:00' })],
    }), { previousLastItem: previousLast })).toThrow('invalid_notification_inbox_page');
  });

  it('binds principal identity to actor, grants and permissions and rejects inactive authority', () => {
    const base = {
      id: 'user-1',
      role: 'readonly',
      is_active: true,
      portfolio_access: 'selected',
      portfolio_access_origin: 'explicit',
      portfolio_ids: ['p2', 'p1'],
      write_permissions: [],
    };
    expect(notificationPrincipalKey(base)).not.toBe(notificationPrincipalKey({
      ...base,
      portfolio_ids: ['p1'],
    }));
    expect(() => validateAuthorityUser({ ...base, is_active: false }))
      .toThrow('invalid_notification_authority');
  });

  it('validates the Phase A personal read response without role or count assumptions', () => {
    const value = validateMarkReadResponse({
      notification_id: 'n1',
      read_at: '2026-10-03T18:10:00.123456+00:00',
    }, 'n1');
    expect(value).toEqual({
      notification_id: 'n1',
      read_at: '2026-10-03T18:10:00.123456+00:00',
    });
    expect(() => validateMarkReadResponse({
      notification_id: 'other',
      read_at: '2026-10-03T18:10:00+00:00',
    }, 'n1')).toThrow('invalid_notification_read_response');
  });
});
