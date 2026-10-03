import { act, render, renderHook, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import useNotificationInbox from '../features/notificationInbox/useNotificationInbox';

const user = (overrides = {}) => ({
  id: 'user-1',
  role: 'readonly',
  is_active: true,
  portfolio_access: 'selected',
  portfolio_access_origin: 'explicit',
  portfolio_ids: ['portfolio-1'],
  write_permissions: [],
  ...overrides,
});

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

const orderedItems = (start, count, startSecond) => Array.from(
  { length: count },
  (_, index) => item(String(start - index), {
    created_at: `2026-10-03T18:00:${String(startSecond - index).padStart(2, '0')}+00:00`,
  }),
);

const page = ({
  items = [item('n1')],
  fullCount = items.length,
  unreadCount = fullCount,
  hasMore = false,
  nextCursor = null,
} = {}) => ({
  items,
  full_count: fullCount,
  unread_count: unreadCount,
  has_more: hasMore,
  next_cursor: nextCursor,
  consistency: 'live',
  snapshot_token: null,
  actions: { mark_all_read: false },
});

function auth(currentUser = user()) {
  return { user: currentUser, updateUser: vi.fn() };
}

function service(overrides = {}) {
  return {
    loadAuthority: vi.fn(async () => user()),
    listInbox: vi.fn(async () => page()),
    markRead: vi.fn(async id => ({
      notification_id: id,
      read_at: '2026-10-03T18:10:00+00:00',
    })),
    ...overrides,
  };
}

describe('useNotificationInbox Phase A', () => {
  it('gates initial inbox publish through fresh /auth/me', async () => {
    const calls = [];
    const currentUser = user();
    const svc = service({
      loadAuthority: vi.fn(async () => { calls.push('auth'); return currentUser; }),
      listInbox: vi.fn(async () => {
        calls.push('inbox');
        return page({ fullCount: 17, unreadCount: 17 });
      }),
    });
    const { result } = renderHook(() => useNotificationInbox({
      auth: auth(currentUser),
      service: svc,
    }));

    await waitFor(() => expect(result.current.phase).toBe('ready'));
    expect(calls).toEqual(['auth', 'inbox']);
    expect(result.current.unreadCount).toBe(17);
    expect(result.current.items).toHaveLength(1);
  });

  it('is neutral on the first render of a changed principal before effects publish', async () => {
    const renders = [];
    let resolveAuthority;
    const firstUser = user();
    const secondUser = user({
      id: 'user-2',
      role: 'techniker',
      portfolio_ids: ['portfolio-2'],
      write_permissions: ['operations'],
    });
    const svc = service({
      loadAuthority: vi.fn()
        .mockResolvedValueOnce(firstUser)
        .mockImplementationOnce(() => new Promise(resolve => { resolveAuthority = resolve; })),
      listInbox: vi.fn(async () => page({ fullCount: 9, unreadCount: 9 })),
    });

    function Probe({ currentAuth }) {
      const state = useNotificationInbox({ auth: currentAuth, service: svc });
      renders.push({ userId: currentAuth.user.id, count: state.unreadCount, phase: state.phase });
      return <span>{state.unreadCount ?? 'neutral'}</span>;
    }

    const view = render(<Probe currentAuth={auth(firstUser)} />);
    expect(await screen.findByText('9')).toBeInTheDocument();
    const before = renders.length;
    view.rerender(<Probe currentAuth={auth(secondUser)} />);
    expect(renders[before]).toMatchObject({ userId: 'user-2', count: null });
    expect(screen.queryByText('9')).not.toBeInTheDocument();
    expect(screen.getByText('neutral')).toBeInTheDocument();

    await act(async () => { resolveAuthority(secondUser); });
  });

  it('updates AuthContext and refuses inbox publish when fresh grants changed', async () => {
    const oldUser = user();
    const freshUser = user({ portfolio_ids: ['portfolio-2'] });
    const currentAuth = auth(oldUser);
    const svc = service({ loadAuthority: vi.fn(async () => freshUser) });
    const { result } = renderHook(() => useNotificationInbox({
      auth: currentAuth,
      service: svc,
    }));

    await waitFor(() => expect(currentAuth.updateUser).toHaveBeenCalledWith(freshUser));
    expect(svc.listInbox).not.toHaveBeenCalled();
    expect(result.current.items).toEqual([]);
    expect(result.current.unreadCount).toBeNull();
  });

  it.each([
    ['access', Object.assign(new Error('forbidden'), { statusCode: 403 })],
    ['unavailable', Object.assign(new Error('network'), { isNetwork: true })],
  ])('clears old private success on %s failure without fake zero', async (kind, failure) => {
    const svc = service();
    const { result } = renderHook(() => useNotificationInbox({ auth: auth(), service: svc }));
    await waitFor(() => expect(result.current.phase).toBe('ready'));
    expect(result.current.unreadCount).toBe(1);

    svc.listInbox.mockRejectedValueOnce(failure);
    await act(async () => { await result.current.refresh(); });

    expect(result.current.phase).toBe('error');
    expect(result.current.errorKind).toBe(kind);
    expect(result.current.items).toEqual([]);
    expect(result.current.unreadCount).toBeNull();
  });

  it('aborts old request and is immediately neutral when actor/service binding changes', async () => {
    let oldSignal;
    const oldService = service({
      loadAuthority: vi.fn(({ signal }) => new Promise((_resolve, reject) => {
        oldSignal = signal;
        signal.addEventListener(
          'abort',
          () => reject(new DOMException('Aborted', 'AbortError')),
          { once: true },
        );
      })),
    });
    const newUser = user({ id: 'user-2', portfolio_ids: ['portfolio-2'] });
    const newService = service({
      loadAuthority: vi.fn(async () => newUser),
      listInbox: vi.fn(async () => page({ items: [], fullCount: 0, unreadCount: 0 })),
    });
    const { result, rerender } = renderHook(
      ({ currentAuth, currentService }) => useNotificationInbox({
        auth: currentAuth,
        service: currentService,
      }),
      {
        initialProps: {
          currentAuth: auth(),
          currentService: oldService,
        },
      },
    );

    await waitFor(() => expect(oldService.loadAuthority).toHaveBeenCalledTimes(1));
    expect(oldSignal.aborted).toBe(false);
    rerender({ currentAuth: auth(newUser), currentService: newService });

    expect(result.current.items).toEqual([]);
    expect(result.current.unreadCount).toBeNull();
    await waitFor(() => expect(oldSignal.aborted).toBe(true));
    await waitFor(() => expect(result.current.phase).toBe('ready'));
    expect(result.current.unreadCount).toBe(0);
  });

  it('neutralizes visible data while loadMore revalidates authority, then appends disjoint page', async () => {
    let resolveSecondAuthority;
    const svc = service({
      loadAuthority: vi.fn()
        .mockResolvedValueOnce(user())
        .mockImplementationOnce(() => new Promise(resolve => { resolveSecondAuthority = resolve; })),
      listInbox: vi.fn()
        .mockResolvedValueOnce(page({
          items: orderedItems(20, 10, 59),
          fullCount: 17,
          unreadCount: 17,
          hasMore: true,
          nextCursor: 'opaque-next',
        }))
        .mockResolvedValueOnce(page({
          items: orderedItems(10, 7, 49),
          fullCount: 17,
          unreadCount: 17,
        })),
    });
    const { result } = renderHook(() => useNotificationInbox({ auth: auth(), service: svc }));
    await waitFor(() => expect(result.current.items).toHaveLength(10));

    let pending;
    act(() => { pending = result.current.loadMore(); });
    expect(result.current.phase).toBe('loading_more');
    expect(result.current.items).toEqual([]);
    expect(result.current.unreadCount).toBeNull();

    await act(async () => {
      resolveSecondAuthority(user());
      await pending;
    });

    expect(result.current.phase).toBe('ready');
    expect(result.current.items).toHaveLength(17);
    expect(result.current.unreadCount).toBe(17);
    expect(svc.listInbox).toHaveBeenNthCalledWith(2, expect.objectContaining({
      status: 'unread',
      after: 'opaque-next',
      limit: 10,
      signal: expect.any(AbortSignal),
    }));
  });

  it('does not combine live pages when exact count changed', async () => {
    const svc = service({
      listInbox: vi.fn()
        .mockResolvedValueOnce(page({
          items: orderedItems(20, 10, 59),
          fullCount: 17,
          unreadCount: 17,
          hasMore: true,
          nextCursor: 'opaque-next',
        }))
        .mockResolvedValueOnce(page({
          items: orderedItems(10, 1, 49),
          fullCount: 18,
          unreadCount: 18,
        })),
    });
    const { result } = renderHook(() => useNotificationInbox({ auth: auth(), service: svc }));
    await waitFor(() => expect(result.current.phase).toBe('ready'));
    await act(async () => { await result.current.loadMore(); });

    expect(result.current.phase).toBe('changed');
    expect(result.current.items).toEqual([]);
    expect(result.current.unreadCount).toBeNull();
  });

  it('allows personal mark-read for readonly solely because item action permits it', async () => {
    const svc = service({
      listInbox: vi.fn()
        .mockResolvedValueOnce(page({ items: [item('n1')], fullCount: 1 }))
        .mockResolvedValueOnce(page({ items: [], fullCount: 0, unreadCount: 0 })),
    });
    const readonlyAuth = auth(user({ role: 'readonly', write_permissions: [] }));
    const { result } = renderHook(() => useNotificationInbox({ auth: readonlyAuth, service: svc }));
    await waitFor(() => expect(result.current.phase).toBe('ready'));

    await act(async () => { await result.current.markRead('n1'); });

    expect(svc.markRead).toHaveBeenCalledWith('n1', expect.objectContaining({
      signal: expect.any(AbortSignal),
    }));
    expect(svc.listInbox).toHaveBeenCalledTimes(2);
    expect(result.current.unreadCount).toBe(0);
  });

  it('does not call personal read when backend item action is false', async () => {
    const svc = service({
      listInbox: vi.fn(async () => page({
        items: [item('n1', { actions: { mark_read: false } })],
        fullCount: 1,
      })),
    });
    const { result } = renderHook(() => useNotificationInbox({ auth: auth(), service: svc }));
    await waitFor(() => expect(result.current.phase).toBe('ready'));

    await act(async () => { expect(await result.current.markRead('n1')).toBe(false); });
    expect(svc.markRead).not.toHaveBeenCalled();
  });
});
