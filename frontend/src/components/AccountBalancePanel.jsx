import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { useAuth } from '../contexts/AuthContext';
import { useTranslation } from '../i18n';
import { euroCents } from '../utils/accountMoney';
import './AccountBalancePanel.css';

const endpoint = (id, suffix, params) => `/accounts/${encodeURIComponent(id)}/${suffix}?${new URLSearchParams(params)}`;
const moneyFields = ['opening_balance_cents', 'comparison_balance_cents', 'bookings_sum_cents', 'income_sum_cents', 'expense_sum_cents', 'calculated_balance_cents', 'difference_cents'];
const validSummary = value => value && value.source_kind === 'stored_account_and_cash_bookings'
  && typeof value.is_computable === 'boolean' && /^[0-9a-f]{64}$/.test(value.source_hash || '')
  && moneyFields.every(key => value[key] === null || (typeof value[key] === 'string' && /^-?\d+$/.test(value[key])))
  && value.is_computable === (value.calculated_balance_cents !== null)
  && Number.isSafeInteger(value.booking_count) && value.booking_count >= 0
  && Number.isSafeInteger(value.issues_count) && value.issues_count >= 0
  && ['open', 'matched', 'booked', 'confirmed', 'other'].every(key => value.status_totals?.[key]
    && Number.isSafeInteger(value.status_totals[key].booking_count)) && Array.isArray(value.issues_sample);

function useRead(path, identity, validate = () => true) {
  const key = `${identity}:${path}`, guard = useRef(validate);
  useEffect(() => { guard.current = validate; }, [validate]);
  const [state, setState] = useState({ key: '', data: null, loading: false, error: null });
  const [attempt, retry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    if (!path) return undefined;
    setState({ key, data: null, loading: true, error: null });
    api.get(path, { signal: controller.signal }).then(data => {
      if (!guard.current(data)) throw new Error('accountBalance.invalidResponse');
      if (!controller.signal.aborted) setState({ key, data, loading: false, error: null });
    }).catch(error => {
      if (!controller.signal.aborted) setState({ key, data: null, loading: false, error });
    });
    return () => controller.abort();
  }, [path, key, attempt]);
  return { ...(state.key === key ? state : { data: null, loading: Boolean(path), error: null }), retry: () => retry(value => value + 1) };
}

function ReadState({ result, t }) {
  if (result.loading) return <p role="status">{t('accountBalance.loading')}</p>;
  if (result.error) return <div className="alert alert-error" role="alert"><p>{result.error.message === 'accountBalance.invalidResponse'
    ? t(result.error.message) : result.error.message}</p><button type="button" className="btn btn-secondary" onClick={result.retry}>{t('ui.buttons.retry')}</button></div>;
  return null;
}

export default function AccountBalancePanel({ initialAccount = '', onClose, onEditAccount, onRepairValues }) {
  const { t, locale } = useTranslation();
  const auth = useAuth();
  const identity = JSON.stringify([auth?.user?.id, auth?.user?.role || auth?.role, auth?.user?.portfolio_access, auth?.user?.portfolio_ids]);
  const [accountId, setAccountId] = useState(initialAccount);
  const [search, setSearch] = useState('');
  const [asOf, setAsOf] = useState('');
  const [cutoff, setCutoff] = useState('');
  const [choiceCursor, setChoiceCursor] = useState('');
  const [view, setView] = useState('bookings');
  const [cursor, setCursor] = useState('');
  const choices = useRead(`/bookings/lookup/accounts?${new URLSearchParams({ search, ...(accountId ? { selected_id: accountId } : {}), page_size: '25', ...(choiceCursor ? { cursor: choiceCursor } : {}) })}`,
    identity, value => value && Array.isArray(value.items));
  const summary = useRead(accountId ? endpoint(accountId, 'balance-summary', cutoff ? { as_of: cutoff } : {}) : null, identity, validSummary);
  const source = useRead(summary.data ? endpoint(accountId, 'balance-sources', { kind: view, source_hash: summary.data.source_hash,
    ...(cutoff ? { as_of: cutoff } : {}), ...(cursor ? { cursor } : {}), page_size: '25' }) : null, identity,
    value => value && Array.isArray(value.items) && typeof value.has_more === 'boolean');
  const heading = useRef(null);
  useEffect(() => { heading.current?.focus(); }, []);
  const pick = id => { setAccountId(id); setCursor(''); setChoiceCursor(''); };
  const current = summary.data;
  const options = choices.data?.items || [];
  const selected = choices.data?.selected;
  const displayOptions = selected && !options.some(item => item.id === selected.id) ? [selected, ...options] : options;
  const switchView = value => { setView(value); setCursor(''); };
  const reloadSummary = () => { setCursor(''); summary.retry(); };

  return <section className="account-balance-panel panel" aria-labelledby="account-balance-title">
    <div className="account-balance-heading"><div><h2 id="account-balance-title" ref={heading} tabIndex={-1}>{t('accountBalance.title')}</h2>
      <p>{t('accountBalance.description')}</p></div><button type="button" className="btn btn-secondary" onClick={onClose}>{t('ui.buttons.close')}</button></div>
    <div className="account-balance-controls">
      <label>{t('accountBalance.searchAccount')}<input type="search" value={search} maxLength={200} onChange={event => { setSearch(event.target.value); setChoiceCursor(''); }} /></label>
      <label>{t('accountBalance.account')}<select value={accountId} onChange={event => pick(event.target.value)}>
        <option value="">{t('accountBalance.chooseAccount')}</option>{displayOptions.map(item => <option value={item.id} key={item.id}>{item.label}</option>)}</select></label>
      <form onSubmit={event => { event.preventDefault(); setCutoff(asOf); setCursor(''); }}>
        <label>{t('accountBalance.asOf')}<input type="date" value={asOf} onChange={event => setAsOf(event.target.value)} /></label>
        <button type="submit" className="btn btn-secondary">{t('accountBalance.applyCutoff')}</button>
      </form>
    </div>
    <ReadState result={choices} t={t} />
    {choices.data?.has_more && <button type="button" className="btn btn-secondary" onClick={() => setChoiceCursor(choices.data.next_cursor)}>{t('accountBalance.moreAccounts')}</button>}
    {!accountId && <p className="text-muted">{t('accountBalance.chooseHint')}</p>}
    <ReadState result={summary} t={t} />
    {current && <>
      <div className="account-balance-facts">
        {[['opening', current.opening_balance_cents], ['cash', current.bookings_sum_cents], ['calculated', current.calculated_balance_cents],
          ['comparison', current.comparison_balance_cents], ['difference', current.difference_cents]].map(([key, value]) => <div key={key} className={`account-balance-fact account-balance-${key}`}>
            <span>{t(`accountBalance.${key}`)}</span><strong>{euroCents(value, locale)}</strong></div>)}
      </div>
      <p className="account-balance-note">{t('accountBalance.undatedNote')}</p>
      <p>{cutoff ? `${t('accountBalance.through')} ${current.as_of}` : t('accountBalance.allStored')} · {current.booking_count} {t('accountBalance.bookingCount')}</p>
      {!current.is_computable && <div className="alert alert-error" role="alert">{t('accountBalance.blocked')}</div>}
      <div className="account-balance-statuses">{['open', 'matched', 'booked', 'confirmed', 'other'].map(status => <div key={status}>
        <span>{t(`accountBalance.status.${status}`)}</span><strong>{euroCents(current.status_totals[status]?.amount_cents, locale)}</strong>
        <small>{current.status_totals[status]?.booking_count ?? '—'} {t('accountBalance.bookingCount')}</small></div>)}</div>
      <p className="text-muted">{t('accountBalance.statusNote')}</p>
      <div className="account-balance-source-actions"><button type="button" className="btn btn-secondary" aria-pressed={view === 'bookings'} onClick={() => switchView('bookings')}>{t('accountBalance.bookings')}</button>
        <button type="button" className="btn btn-secondary" aria-pressed={view === 'issues'} onClick={() => switchView('issues')}>{t('accountBalance.issues')} ({current.issues_count})</button>
        <button type="button" className="btn btn-secondary" onClick={reloadSummary}>{t('accountBalance.refresh')}</button>
        {onEditAccount && <button type="button" className="btn btn-secondary" onClick={() => onEditAccount(accountId)}>{t('accountBalance.editAccount')}</button>}
        {onRepairValues && typeof current.account_updated_at === 'string' && (current.opening_balance_cents === null || current.comparison_balance_cents === null)
          && <button type="button" className="btn btn-secondary" onClick={() => onRepairValues(current)}>{t('accountBalance.repairValues')}</button>}
        <a className="btn btn-secondary" href={`/bookings?account_id=${encodeURIComponent(accountId)}`}>{t('accountBalance.manageBookings')}</a></div>
      <ReadState result={source.error?.code === 'balance_source_changed' ? { ...source, retry: reloadSummary } : source} t={t} />
      {source.data && <div className="account-balance-sources">
        {source.data.items.length === 0 ? <p>{t(view === 'issues' ? 'accountBalance.noIssues' : 'accountBalance.noBookings')}</p>
          : view === 'issues' ? <ul>{source.data.items.map(issue => <li key={`${issue.source_type}:${issue.source_id}:${issue.field}`}>
            <strong>{t(`accountBalance.issue.${issue.code}`)}</strong><span>{t(`accountBalance.field.${issue.field}`)} · <code>{issue.source_id}</code></span>
            <span>{t('accountBalance.storedValue')}: <code>{issue.value_preview}</code></span><small>{t(`accountBalance.repair.${issue.repair}`)}</small></li>)}</ul>
            : <div className="account-balance-table-scroll"><table><caption>{t('accountBalance.sourceCaption')}</caption><thead><tr><th>{t('accountBalance.date')}</th><th>{t('accountBalance.text')}</th>
              <th>{t('accountBalance.amount')}</th><th>{t('accountBalance.classification')}</th></tr></thead><tbody>{source.data.items.map(row => <tr key={row.id}>
                <td>{row.booking_date}</td><td>{row.payment_text || '—'}<small><code>{row.id}</code></small></td><td>{euroCents(row.amount_cents, locale)}</td>
                <td>{t(`accountBalance.status.${['open', 'matched', 'booked', 'confirmed'].includes(row.status) ? row.status : 'other'}`)}{!row.valid_amount && <span>{t('accountBalance.invalidAmount')}</span>}</td></tr>)}</tbody></table></div>}
        <div className="account-balance-pagination">{cursor && <button type="button" className="btn btn-secondary" onClick={() => setCursor('')}>{t('accountBalance.firstPage')}</button>}
          {source.data.has_more && <button type="button" className="btn btn-secondary" onClick={() => setCursor(source.data.next_cursor)}>{t('accountBalance.nextPage')}</button>}
          <span>{t('accountBalance.sourceCount')}: {source.data.source_count}</span></div>
      </div>}
      <details className="account-balance-proof"><summary>{t('accountBalance.proof')}</summary><dl><dt>{t('accountBalance.snapshot')}</dt><dd>{current.snapshot_started_at}</dd>
        <dt>{t('accountBalance.fingerprint')}</dt><dd><code>{current.source_hash}</code></dd><dt>{t('accountBalance.range')}</dt><dd>{current.first_booking_date || '—'} → {current.last_booking_date || '—'}</dd></dl></details>
    </>}
  </section>;
}
