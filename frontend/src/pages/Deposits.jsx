import { useCallback, useEffect, useId, useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import { useTranslation } from '../i18n';
import { PartyLink } from '../features/partyWorkspace/PartyWorkspace';
import DepositFile from '../features/deposits/DepositFile';
import DepositsDialog from '../features/deposits/DepositsDialog';
import { depositService } from '../features/deposits/depositApi';
import { depositText } from '../features/deposits/depositText';
import { formatDate, formatMoney } from '../utils/format';
import { mayWrite } from '../utils/permissions';
import '../features/deposits/deposits.css';

const STAGES = ['agreed', 'partially_received', 'received', 'settlement_draft', 'retained', 'settled', 'closed',
  'provided', 'released'];
const PAGE = 50;

/** Every deposit file the account may see, with what was received and where it stands; all counted, paged. */
export default function Deposits({ service = depositService }) {
  const { locale } = useTranslation();
  const say = useCallback((key, params) => depositText(locale, key, params), [locale]);
  const auth = useAuth();
  const canEdit = mayWrite(auth?.write ?? null, '/deposits');
  const store = useDataStore();
  const { items: contracts } = useEntities('contracts', '/contracts');
  const id = useId();
  const [query, setQuery] = useState('');
  const [stage, setStage] = useState('');
  const [skip, setSkip] = useState(0);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(null);
  const [contractId, setContractId] = useState('');
  const [contractDialog, setContractDialog] = useState(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      service.files({ stage, query: query.trim(), skip, limit: PAGE }, { signal: controller.signal })
        .then(value => { if (!controller.signal.aborted) { setData(value); setError(null); } })
        .catch(failure => { if (!controller.signal.aborted && failure?.name !== 'AbortError') setError(failure?.message || say('loadFailed')); });
    }, query ? 250 : 0);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [attempt, query, say, service, skip, stage]);

  const changed = useCallback(() => {
    setAttempt(value => value + 1);
    store?.invalidateRelated('deposits', 'bookings', 'receivables', 'documents');
  }, [store]);

  const rows = data?.items || [];
  const total = data?.total ?? 0;

  return <div className="page">
    <div className="page-header"><h1>{say('pageTitle')}</h1></div>
    {error && <div className="alert alert-error" role="alert">{error}{' '}
      <button type="button" className="btn btn-secondary btn-sm" onClick={() => setAttempt(v => v + 1)}>{say('retry')}</button></div>}
    <div className="deposits-page__filters">
      <label htmlFor={`${id}-q`}>{say('search')}
        <input id={`${id}-q`} type="search" value={query} onChange={event => { setQuery(event.target.value); setSkip(0); }} /></label>
      <label htmlFor={`${id}-stage`}>{say('stage')}
        <select id={`${id}-stage`} value={stage} onChange={event => { setStage(event.target.value); setSkip(0); }}>
          <option value="">{say('allStages')}</option>
          {STAGES.map(value => <option key={value} value={value}>{say(`stage_${value}`)}{data?.stages?.[value] != null ? ` (${data.stages[value]})` : ''}</option>)}
        </select></label>
      {canEdit && <label htmlFor={`${id}-contract`}>{say('contract')}
        <select id={`${id}-contract`} value={contractId} onChange={event => setContractId(event.target.value)}>
          <option value="">—</option>
          {contracts.map(contract => <option key={contract.id} value={contract.id}>{contract.contract_number || contract.id}</option>)}
        </select></label>}
      {canEdit && <button type="button" className="btn btn-primary" disabled={!contractId}
        onClick={() => setContractDialog(contractId)}>{say('newAgreement')}</button>}
    </div>
    {data && <p className="deposits-page__totals">
      <span>{say('count', { count: data.totals.count })}</span>
      <span>{say('amount')}: {formatMoney(data.totals.amount)}</span>
      <span>{say('received')}: {formatMoney(data.totals.received)}</span>
      {data.totals.retention > 0 && <span>{say('retention')}: {formatMoney(data.totals.retention)}</span>}
    </p>}
    {!data && !error && <p role="status">{say('loading')}</p>}
    {data && <div className="deposits-page__table-wrap"><table className="deposits-page__table">
      <thead><tr><th scope="col">{say('contract')}</th><th scope="col">{say('tenant')}</th><th scope="col">{say('property')}</th>
        <th scope="col">{say('form')}</th><th scope="col">{say('amount')}</th><th scope="col">{say('received')}</th>
        <th scope="col">{say('stage')}</th><th scope="col"><span className="deposit__sr">{say('open')}</span></th></tr></thead>
      <tbody>{rows.length === 0 ? <tr><td colSpan={8}>{say('none')}</td></tr> : rows.map(row => <tr key={row.id}>
        <td data-label={say('contract')}>{row.contract_number}{row.contract_end && <small>{formatDate(row.contract_end)}</small>}</td>
        <td data-label={say('tenant')}>{row.tenant_id ? <PartyLink tenantId={row.tenant_id}>{row.tenant_name || '—'}</PartyLink> : '—'}</td>
        <td data-label={say('property')}>{row.property_name || '—'}{row.unit_label && <small>{row.unit_label}</small>}</td>
        <td data-label={say('form')}>{say(`form_${row.form}`)}</td>
        <td data-label={say('amount')}>{formatMoney(row.amount)}</td>
        <td data-label={say('received')}>{formatMoney(row.received)}{row.retention > 0 && <small>{say('retention')} {formatMoney(row.retention)}</small>}</td>
        <td data-label={say('stage')}><span className={`deposit__stage deposit__stage--${row.stage}`}>{say(`stage_${row.stage}`)}</span></td>
        <td><button type="button" className="btn btn-secondary btn-sm" onClick={() => setOpen(row.id)}
          aria-label={`${say('open')}: ${row.contract_number}`}>{say('open')}</button></td>
      </tr>)}</tbody>
    </table></div>}
    {total > PAGE && <div className="deposits-page__pager">
      <span>{say('pageOf', { from: skip + 1, to: Math.min(skip + PAGE, total), total })}</span>
      <button type="button" className="btn btn-secondary btn-sm" disabled={skip === 0} onClick={() => setSkip(Math.max(0, skip - PAGE))}>{say('previous')}</button>
      <button type="button" className="btn btn-secondary btn-sm" disabled={skip + PAGE >= total} onClick={() => setSkip(skip + PAGE)}>{say('next')}</button>
    </div>}
    {open && <DepositFile key={open} depositId={open} service={service} onClose={() => setOpen(null)} onChanged={changed} />}
    {contractDialog && <DepositsDialog contractId={contractDialog} service={service} onClose={() => setContractDialog(null)} onChanged={changed} />}
  </div>;
}
