import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import { accessDenied, count } from './dashboardModel';

const finite = value => typeof value === 'number' && Number.isFinite(value);
const near = (a, b) => Math.abs(a - b) <= .011;
const list = (data, validate) => Array.isArray(data) && data.every(item => item && typeof item === 'object' && validate(item));
export const bucketKeys = ['current', 'days1to30', 'days31to60', 'days61to90', 'days90plus'];
const config = {
  cashflow: { path: '/reports/cashflow', valid: data => data && ['incomeTotal', 'expenseTotal', 'netTotal'].every(key => finite(data[key])) && data.incomeTotal >= 0 && data.expenseTotal >= 0 && near(data.incomeTotal - data.expenseTotal, data.netTotal) },
  aging: { path: '/reports/receivables-aging', initial: true, valid: data => data && finite(data.openTotal) && data.openTotal >= 0 && bucketKeys.every(key => finite(data.buckets?.[key]) && data.buckets[key] >= 0) && near(bucketKeys.reduce((sum, key) => sum + data.buckets[key], 0), data.openTotal) },
  maintenance: { path: '/reports/maintenance-costs', initial: true, valid: data => data && count(data.openCases) && finite(data.totalEstimatedCost) && list(data.categories, item => typeof item.category === 'string' && finite(item.estimatedCost)) && near(data.categories.reduce((sum, item) => sum + item.estimatedCost, 0), data.totalEstimatedCost) },
  forecast: { path: '/reports/liquidity-forecast?months=6', valid: data => data && finite(data.current_balance) && list(data.forecast, item => /^\d{4}-\d{2}$/.test(item.month) && ['projected_balance', 'projected_income', 'projected_expense'].every(key => finite(item[key]))) },
  finance: { path: '/reports/finance', valid: data => data && finite(data.uncategorizedTotal) && finite(data.bookingsTotal) && list(data.totalsByCategory, item => typeof item.categoryName === 'string' && finite(item.total)) && near(data.totalsByCategory.reduce((sum, item) => sum + item.total, data.uncategorizedTotal), data.bookingsTotal) },
  audit: { path: '/audit?limit=10', valid: data => list(Array.isArray(data) ? data : data?.items, item => typeof item.action === 'string') },
};
const initial = () => Object.fromEntries(Object.keys(config).map(key => [key, { status: 'idle', data: null, error: null, loadedAt: null }]));

/** These separate reports do not share the dashboard summary's read snapshot. */
export default function useDashboardReports(principal, onDenied) {
  const [state, setState] = useState(() => ({ principal, sources: initial() }));
  const current = useRef(state); const controllers = useRef({}); const alive = useRef(false);
  const publish = useCallback(value => { current.current = value; setState(value); }, []);
  const reload = useCallback(async key => {
    if (!principal || !config[key]) return;
    controllers.current[key]?.abort(); const controller = new AbortController(); controllers.current[key] = controller;
    const previous = current.current.principal === principal ? current.current.sources : initial();
    publish({ principal, sources: { ...previous, [key]: { ...previous[key], status: 'loading', error: null } } });
    try {
      const data = await api.get(config[key].path, { signal: controller.signal });
      if (!config[key].valid(data)) throw new Error('dashboard_summary_invalid');
      if (!alive.current || controller.signal.aborted) return;
      publish({ principal, sources: { ...current.current.sources, [key]: { status: 'ready', data, error: null, loadedAt: new Date() } } });
    } catch (error) {
      if (!alive.current || controller.signal.aborted) return;
      if (accessDenied(error)) {
        Object.values(controllers.current).forEach(request => request.abort());
        publish({ principal, sources: initial() }); onDenied?.(error);
      } else publish({ principal, sources: { ...current.current.sources, [key]: { ...current.current.sources[key], status: 'error', error } } });
    }
  }, [principal, onDenied, publish]);
  useEffect(() => {
    alive.current = true;
    if (principal) Object.keys(config).filter(key => config[key].initial).forEach(key => { void reload(key); });
    const active = controllers.current;
    return () => { alive.current = false; Object.values(active).forEach(controller => controller.abort()); };
  }, [principal, reload]);
  const sources = state.principal === principal ? state.sources : initial();
  const loadAnalysis = () => ['cashflow', 'forecast', 'finance'].filter(key => current.current.sources[key].status === 'idle').forEach(key => { void reload(key); });
  const reloadAll = () => Object.keys(config).filter(key => config[key].initial || current.current.sources[key].status !== 'idle').forEach(key => { void reload(key); });
  return { sources, reload, reloadAll, loadAnalysis };
}
