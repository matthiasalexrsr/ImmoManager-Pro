import { useAuth } from '../../contexts/AuthContext';
import { useTranslation } from '../../i18n';
import { inboxUtcDate } from './notificationInboxModel';
import useNotificationInbox from './useNotificationInbox';
import { notificationInboxService } from './notificationInboxApi';
import { inboxText } from './notificationInboxText';
import './NotificationInbox.css';

function dateTime(value, locale, tr) {
  if (value == null) return tr('unknownDate');
  try {
    return new Intl.DateTimeFormat(locale, {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(inboxUtcDate(value));
  } catch {
    return tr('unknownDate');
  }
}

function errorMessage(state, locale) {
  const tr = (key, params) => inboxText(locale, key, params);
  return tr({
    access: 'access',
    unavailable: 'unavailable',
    invalid: 'invalid',
    request: 'request',
  }[state.errorKind] || 'request');
}

export function NotificationInboxView({
  state,
  locale = 'de-DE',
  onRetry,
  onLoadMore,
  onMarkRead,
}) {
  const tr = (key, params) => inboxText(locale, key, params);

  if (['loading', 'loading_more', 'acting', 'idle'].includes(state.phase)) {
    return (
      <section className="notification-inbox-panel" aria-label={tr('title')}>
        <p className="notification-inbox-state" role="status">{tr('loading')}</p>
      </section>
    );
  }

  if (state.phase === 'changed') {
    return (
      <section className="notification-inbox-panel" aria-label={tr('title')}>
        <div className="notification-inbox-changed" role="status">
          <p>{tr('changed')}</p>
          <button type="button" className="btn btn-secondary" onClick={onRetry}>
            {tr('reload')}
          </button>
        </div>
      </section>
    );
  }

  if (state.phase === 'error') {
    return (
      <section className="notification-inbox-panel" aria-label={tr('title')}>
        <div className="notification-inbox-error" role="alert">
          <p>{errorMessage(state, locale)}</p>
          <button type="button" className="btn btn-secondary" onClick={onRetry}>
            {tr('retry')}
          </button>
        </div>
      </section>
    );
  }

  const empty = state.phase === 'ready' && state.unreadCount === 0;
  return (
    <section className="notification-inbox-panel" aria-label={tr('title')}>
      <header className="notification-inbox-header">
        <div>
          <strong>{tr('title')}</strong>
          <span>{tr('unread', { count: state.unreadCount })}</span>
        </div>
      </header>

      {empty ? (
        <p className="notification-inbox-empty" role="status">{tr('empty')}</p>
      ) : (
        <ul className="notification-inbox-list">
          {state.items.map(item => (
            <li key={item.id} className={`notification-inbox-item notification-inbox-item--${item.severity}`}>
              <div className="notification-inbox-item__content">
                <strong>{item.title}</strong>
                <p>{item.content}</p>
                <time dateTime={item.created_at || undefined}>
                  {dateTime(item.created_at, locale, tr)}
                </time>
              </div>
              {item.actions?.mark_read && (
                <button type="button" className="btn btn-secondary btn-sm"
                  disabled={state.busy} onClick={() => onMarkRead(item.id)}>
                  {tr('markRead')}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {state.phase === 'loading_more' && (
        <p className="notification-inbox-state" role="status">{tr('loading')}</p>
      )}

      {state.hasMore && (
        <button type="button" className="btn btn-secondary notification-inbox-more"
          disabled={state.busy} onClick={onLoadMore}>
          {tr('loadMore')}
        </button>
      )}
    </section>
  );
}

export default function NotificationInboxPanel({
  service = notificationInboxService,
  pageSize = 10,
  autoLoad = true,
}) {
  const auth = useAuth();
  const { locale } = useTranslation();
  const state = useNotificationInbox({ auth, service, pageSize, autoLoad });

  return (
    <NotificationInboxView
      state={state}
      locale={locale}
      onRetry={state.refresh}
      onLoadMore={state.loadMore}
      onMarkRead={state.markRead}
    />
  );
}
