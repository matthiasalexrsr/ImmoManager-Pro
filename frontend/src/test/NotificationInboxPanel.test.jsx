import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { NotificationInboxView } from '../features/notificationInbox/NotificationInboxPanel';

const ready = (overrides = {}) => ({
  phase: 'ready',
  items: [],
  fullCount: 0,
  unreadCount: 0,
  hasMore: false,
  nextCursor: null,
  consistency: 'live',
  actions: { mark_all_read: false },
  busy: false,
  errorKind: null,
  ...overrides,
});
const item = (id, action = true) => ({
  id,
  notification_type: 'task_due',
  title: `Aufgabe ${id}`,
  content: `Inhalt ${id}`,
  severity: 'warning',
  entity_type: 'task',
  entity_id: `task-${id}`,
  created_at: '2026-10-03T18:00:00+00:00',
  read_at: null,
  actions: { mark_read: action },
});

describe('NotificationInboxView Phase A', () => {
  it('shows loading, error and empty states without fake count', () => {
    const view = render(<NotificationInboxView state={{ phase: 'loading' }} onRetry={vi.fn()} />);
    expect(screen.getByRole('status')).toHaveTextContent('Benachrichtigungen werden geprüft');

    view.rerender(<NotificationInboxView
      state={{ phase: 'error', errorKind: 'unavailable' }}
      onRetry={vi.fn()}
    />);
    expect(screen.getByRole('alert')).toHaveTextContent('konnten nicht aktualisiert werden');
    expect(screen.queryByText(/ungelesen insgesamt/)).not.toBeInTheDocument();

    view.rerender(<NotificationInboxView state={ready()} onRetry={vi.fn()} />);
    expect(screen.getByRole('status')).toHaveTextContent('Keine ungelesenen');
    expect(screen.getByText('0 ungelesen insgesamt')).toBeInTheDocument();
  });

  it('shows exact full count while rendering only the bounded page', () => {
    render(<NotificationInboxView
      state={ready({
        items: Array.from({ length: 10 }, (_, index) => item(String(index + 1))),
        fullCount: 37,
        unreadCount: 37,
        hasMore: true,
        nextCursor: 'opaque-next',
      })}
      onLoadMore={vi.fn()}
      onMarkRead={vi.fn()}
    />);
    expect(screen.getByText('37 ungelesen insgesamt')).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(10);
    expect(screen.getByRole('button', { name: 'Weitere laden' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Alle als gelesen markieren' })).not.toBeInTheDocument();
  });

  it('renders personal read action solely from backend item action', () => {
    const markRead = vi.fn();
    render(<NotificationInboxView
      state={ready({
        items: [item('allowed', true), item('blocked', false)],
        fullCount: 2,
        unreadCount: 2,
      })}
      onMarkRead={markRead}
    />);
    const buttons = screen.getAllByRole('button', { name: 'Als gelesen markieren' });
    expect(buttons).toHaveLength(1);
    fireEvent.click(buttons[0]);
    expect(markRead).toHaveBeenCalledWith('allowed');
  });

  it('shows only neutral loading while fresh authority is being checked', () => {
    render(<NotificationInboxView state={{
      phase: 'loading_more',
      items: [item('old')],
      fullCount: 1,
      unreadCount: 1,
      hasMore: true,
      nextCursor: 'opaque-next',
      actions: { mark_all_read: false },
    }} />);
    expect(screen.getByRole('status')).toHaveTextContent('Benachrichtigungen werden geprüft');
    expect(screen.queryByText('Aufgabe old')).not.toBeInTheDocument();
    expect(screen.queryByText('1 ungelesen insgesamt')).not.toBeInTheDocument();
  });

  it('shows changed state as reloadable, not as empty', () => {
    const retry = vi.fn();
    render(<NotificationInboxView
      state={{ phase: 'changed', errorKind: 'changed' }}
      onRetry={retry}
    />);
    expect(screen.getByRole('status')).toHaveTextContent('während des Ladens geändert');
    fireEvent.click(screen.getByRole('button', { name: 'Inbox neu laden' }));
    expect(retry).toHaveBeenCalledTimes(1);
  });
});
