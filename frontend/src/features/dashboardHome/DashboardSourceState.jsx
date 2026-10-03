import { RefreshCw } from 'lucide-react';

export default function DashboardSourceState({ source, name, onRetry, onReset, t, locale }) {
  const stale = source.data && source.status !== 'ready';
  const time = source.loadedAt && new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit' }).format(source.loadedAt);
  const message = source.error?.message === 'dashboard_summary_invalid' ? t('dashboardHome.invalidResponse') : source.error?.message || t('dashboardHome.loadError');
  return <>
    {stale && <p className="dashboard-home-stale" role="status">{t('dashboardHome.staleAt', { time })}</p>}
    {source.status === 'error' ? <div className="dashboard-home-state dashboard-home-error" role="alert"><div><strong>{name}: {t('dashboardHome.loadError')}</strong><p>{message}</p>{source.error?.statusCode === 422 && onReset && <p>{t('dashboardHome.pageExpired')}</p>}</div><button className="btn btn-secondary btn-sm" onClick={source.error?.statusCode === 422 && onReset ? onReset : onRetry}><RefreshCw size={15} aria-hidden="true" />{t(source.error?.statusCode === 422 && onReset ? 'dashboardHome.restartPages' : 'dashboardHome.retry')}</button></div>
      : source.status !== 'ready' && <p className="dashboard-home-state" role="status">{t('dashboardHome.loading')} <span>{name}</span></p>}
  </>;
}
