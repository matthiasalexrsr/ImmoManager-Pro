import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import { useAuth } from '../../contexts/AuthContext';
import { useTranslation } from '../../i18n';
import { principalKey } from '../unitInventory/read';
import { accessDenied, text } from './dashboardModel';

/** ProtectedRoute validates initial entry. Focus and refresh recheck current grants. */
export default function DashboardBoundary({ children }) {
  const { user, updateUser } = useAuth() || {}; const { t } = useTranslation();
  const principal = principalKey(user); const [blocked, setBlocked] = useState(null); const [check, setCheck] = useState(null);
  const checking = check?.principal === principal && check.pending;
  const request = useRef(null);
  const onDenied = useCallback(error => { request.current?.abort(); setCheck(null); setBlocked({ principal, error }); }, [principal]);
  const verify = useCallback(async () => {
    request.current?.abort(); const controller = new AbortController(); request.current = controller; setCheck({ principal, pending: true });
    try {
      const current = await api.get('/auth/me', { signal: controller.signal });
      if (controller.signal.aborted) return false;
      if (!text(current?.id) || !text(current?.role)) throw new Error('dashboard_summary_invalid');
      if (principalKey(current) !== principal) {
        setBlocked({ principal, error: new Error('dashboard_access_changed') }); updateUser?.(current); return false;
      }
      updateUser?.(current); setBlocked(null); return true;
    } catch (error) {
      if (!controller.signal.aborted) setBlocked({ principal, error }); return false;
    } finally { if (!controller.signal.aborted) setCheck({ principal, pending: false }); }
  }, [principal, updateUser]);
  useEffect(() => {
    const refreshAuthority = () => { if (document.visibilityState === 'visible') void verify(); };
    window.addEventListener('focus', refreshAuthority); document.addEventListener('visibilitychange', refreshAuthority);
    return () => { request.current?.abort(); window.removeEventListener('focus', refreshAuthority); document.removeEventListener('visibilitychange', refreshAuthority); };
  }, [verify]);
  const failure = blocked?.principal === principal ? blocked.error : null;
  if (!principal || failure) return <div className="page dashboard-home"><h1>{t('dashboardHome.title')}</h1><div className="dashboard-home-state dashboard-home-error" role="alert"><p>{t(failure?.message === 'dashboard_summary_invalid' ? 'dashboardHome.invalidResponse' : !principal || accessDenied(failure) || failure?.message === 'dashboard_access_changed' ? 'dashboardHome.accessChanged' : 'dashboardHome.accessUnavailable')}</p>{principal && <button className="btn btn-secondary" disabled={checking} onClick={() => { void verify(); }}>{t('dashboardHome.checkAccess')}</button>}</div></div>;
  return children({ principal, onDenied, verify, verifying: checking });
}
