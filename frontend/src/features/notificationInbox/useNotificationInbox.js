import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  INBOX_PAGE_SIZE,
  emptyInboxState,
  notificationErrorKind,
  notificationPrincipalKey,
  validateInboxPage,
} from './notificationInboxModel';
import { notificationInboxService } from './notificationInboxApi';

function sameBinding(state, principal, service) {
  return state.principal === principal && state.service === service;
}

export default function useNotificationInbox({
  auth,
  service = notificationInboxService,
  pageSize = INBOX_PAGE_SIZE,
  autoLoad = true,
} = {}) {
  const principal = notificationPrincipalKey(auth?.user);
  const updateUserRef = useRef(auth?.updateUser);
  const principalRef = useRef(principal);
  const serviceRef = useRef(service);
  const requestRef = useRef(null);
  const generationRef = useRef(0);
  updateUserRef.current = auth?.updateUser;
  principalRef.current = principal;
  serviceRef.current = service;

  const [stored, setStored] = useState(() => emptyInboxState('', service, 'idle'));

  const visible = useMemo(() => {
    if (sameBinding(stored, principal, service)) return stored;
    return emptyInboxState(principal, service, principal && autoLoad ? 'loading' : 'idle');
  }, [autoLoad, principal, service, stored]);

  const current = useCallback((ticket, expectedPrincipal, expectedService, controller) => (
    !controller.signal.aborted
    && generationRef.current === ticket
    && principalRef.current === expectedPrincipal
    && serviceRef.current === expectedService
  ), []);

  const begin = useCallback((phase) => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    const ticket = ++generationRef.current;
    const expectedPrincipal = principalRef.current;
    const expectedService = serviceRef.current;
    setStored(emptyInboxState(expectedPrincipal, expectedService, phase));
    return { controller, ticket, expectedPrincipal, expectedService };
  }, []);

  const publishChanged = useCallback((expectedPrincipal, expectedService, ticket, controller, error = null) => {
    if (!current(ticket, expectedPrincipal, expectedService, controller)) return;
    setStored({
      ...emptyInboxState(expectedPrincipal, expectedService, 'changed'),
      error,
      errorKind: 'changed',
    });
  }, [current]);

  const publishError = useCallback((error, expectedPrincipal, expectedService, ticket, controller) => {
    if (!current(ticket, expectedPrincipal, expectedService, controller)) return;
    const kind = notificationErrorKind(error);
    if (kind === 'changed') {
      publishChanged(expectedPrincipal, expectedService, ticket, controller, error);
      return;
    }
    setStored({
      ...emptyInboxState(expectedPrincipal, expectedService, 'error'),
      error,
      errorKind: kind,
    });
  }, [current, publishChanged]);

  const freshAuthority = useCallback(async (
    expectedPrincipal,
    expectedService,
    ticket,
    controller,
  ) => {
    const freshUser = await expectedService.loadAuthority({ signal: controller.signal });
    const freshPrincipal = notificationPrincipalKey(freshUser);
    if (!current(ticket, expectedPrincipal, expectedService, controller)) return { ok: false };

    if (freshPrincipal !== expectedPrincipal) {
      setStored(emptyInboxState(freshPrincipal, expectedService, 'idle'));
      updateUserRef.current?.(freshUser);
      return { ok: false, changed: true };
    }
    return { ok: true, user: freshUser };
  }, [current]);

  const refresh = useCallback(async () => {
    const expectedPrincipal = principalRef.current;
    const expectedService = serviceRef.current;
    if (!expectedPrincipal) {
      requestRef.current?.abort();
      ++generationRef.current;
      setStored(emptyInboxState('', expectedService, 'idle'));
      return false;
    }

    const { controller, ticket } = begin('loading');
    try {
      const authority = await freshAuthority(
        expectedPrincipal,
        expectedService,
        ticket,
        controller,
      );
      if (!authority.ok) return false;

      const page = await expectedService.listInbox({
        status: 'unread',
        after: null,
        limit: pageSize,
        signal: controller.signal,
      });
      if (!current(ticket, expectedPrincipal, expectedService, controller)) return false;

      setStored({
        principal: expectedPrincipal,
        service: expectedService,
        phase: 'ready',
        items: page.items,
        fullCount: page.full_count,
        unreadCount: page.unread_count,
        hasMore: page.has_more,
        nextCursor: page.next_cursor,
        consistency: page.consistency,
        error: null,
        errorKind: null,
      });
      return true;
    } catch (error) {
      if (error?.name !== 'AbortError') {
        publishError(error, expectedPrincipal, expectedService, ticket, controller);
      }
      return false;
    } finally {
      if (requestRef.current === controller) requestRef.current = null;
    }
  }, [begin, current, freshAuthority, pageSize, publishError]);

  const loadMore = useCallback(async () => {
    const expectedPrincipal = principalRef.current;
    const expectedService = serviceRef.current;
    const state = sameBinding(stored, expectedPrincipal, expectedService) ? stored : null;
    if (!state || state.phase !== 'ready' || !state.hasMore || !state.nextCursor) return false;

    const { controller, ticket } = begin('loading_more');
    try {
      const authority = await freshAuthority(
        expectedPrincipal,
        expectedService,
        ticket,
        controller,
      );
      if (!authority.ok) return false;

      const raw = await expectedService.listInbox({
        status: 'unread',
        after: state.nextCursor,
        limit: pageSize,
        signal: controller.signal,
      });
      const page = validateInboxPage(raw, {
        status: 'unread',
        expectedConsistency: 'live',
        previousLastItem: state.items.at(-1) || null,
      });
      if (!current(ticket, expectedPrincipal, expectedService, controller)) return false;

      if (page.full_count !== state.fullCount || page.unread_count !== state.unreadCount) {
        publishChanged(expectedPrincipal, expectedService, ticket, controller);
        return false;
      }

      const existing = new Set(state.items.map(item => item.id));
      if (page.items.some(item => existing.has(item.id))) {
        throw new Error('invalid_notification_inbox_page');
      }

      setStored({
        principal: expectedPrincipal,
        service: expectedService,
        phase: 'ready',
        items: [...state.items, ...page.items],
        fullCount: page.full_count,
        unreadCount: page.unread_count,
        hasMore: page.has_more,
        nextCursor: page.next_cursor,
        consistency: page.consistency,
        error: null,
        errorKind: null,
      });
      return true;
    } catch (error) {
      if (error?.name !== 'AbortError') {
        publishError(error, expectedPrincipal, expectedService, ticket, controller);
      }
      return false;
    } finally {
      if (requestRef.current === controller) requestRef.current = null;
    }
  }, [begin, current, freshAuthority, pageSize, publishChanged, publishError, stored]);

  const markRead = useCallback(async (id) => {
    const expectedPrincipal = principalRef.current;
    const expectedService = serviceRef.current;
    const state = sameBinding(stored, expectedPrincipal, expectedService) ? stored : null;
    const item = state?.items.find(candidate => candidate.id === id);
    if (!item?.actions?.mark_read) return false;

    const { controller, ticket } = begin('acting');
    try {
      const authority = await freshAuthority(
        expectedPrincipal,
        expectedService,
        ticket,
        controller,
      );
      if (!authority.ok) return false;
      await expectedService.markRead(id, { signal: controller.signal });
      if (!current(ticket, expectedPrincipal, expectedService, controller)) return false;
    } catch (error) {
      if (error?.name !== 'AbortError') {
        publishError(error, expectedPrincipal, expectedService, ticket, controller);
      }
      return false;
    } finally {
      if (requestRef.current === controller) requestRef.current = null;
    }
    return refresh();
  }, [begin, current, freshAuthority, publishError, refresh, stored]);

  useEffect(() => {
    if (!principal) {
      requestRef.current?.abort();
      ++generationRef.current;
      setStored(emptyInboxState('', service, 'idle'));
      return undefined;
    }
    if (autoLoad) void refresh();
    return () => {
      requestRef.current?.abort();
    };
  }, [autoLoad, principal, refresh, service]);

  return {
    ...visible,
    refresh,
    loadMore,
    markRead,
    busy: ['loading', 'loading_more', 'acting'].includes(visible.phase),
  };
}
