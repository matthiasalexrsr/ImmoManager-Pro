import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useCanWrite } from '../contexts/AuthContext';
import FormModal from '../components/FormModal';
import { useConfirm } from '../components/ConfirmDialog';
import { formatDate, formatMoney, formatPercent } from '../utils/format';
import {
  STATUS_BADGE, contractFields, contractPayload, deadlineLabel, intervalLabel, noticeToLabel, noticeUnitLabel,
  renewalLabel, statusLabel, typeLabel,
} from '../features/serviceContracts/model';
import { DeadlinesTab, LocationsTab, TariffsTab } from '../features/serviceContracts/ContractTabs';
import FinanceTab from '../features/serviceContracts/FinanceTab';
import DocumentsTab from '../features/serviceContracts/DocumentsTab';
import '../features/serviceContracts/serviceContracts.css';
import './propertyDossier.css';

const TAB_KEYS = ['master', 'locations', 'tariffs', 'deadlines', 'finance', 'documents'];

export default function ServiceContractDetail() {
  const { id } = useParams();
  return <ServiceContractDossier key={id} id={id} />;
}

function ServiceContractDossier({ id }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const confirm = useConfirm();
  const [contract, setContract] = useState(null);
  const [error, setError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [tab, setTab] = useState('master');
  const [modal, setModal] = useState(null);     // edit | cancel
  const [contacts, setContacts] = useState([]);
  const [revision, setRevision] = useState(0);
  const path = `/service-contracts/${encodeURIComponent(id)}`;
  const mayChange = useCanWrite('/service-contracts');
  const mayBook = useCanWrite(`${path}/payments`);
  const canWrite = mayChange && contract && !contract.restricted;
  const canBook = (mayChange || mayBook) && contract && !contract.restricted;

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    api.get(path, { signal: controller.signal }).then(setContract)
      .catch(failure => { if (failure.name !== 'AbortError') setError(failure.message); });
    return () => controller.abort();
  }, [path, revision]);

  const reload = () => setRevision(value => value + 1);
  const editFields = useMemo(() => contractFields(t, { contacts, withLocation: false }), [t, contacts]);
  const cancelFields = useMemo(() => [
    { key: 'cancelled_on', label: t('serviceContracts.fields.cancelledOn'), type: 'date', required: true,
      hint: t('serviceContracts.hints.cancelledOn') },
    { key: 'effective_date', label: t('serviceContracts.fields.effectiveDate'), type: 'date',
      hint: t('serviceContracts.hints.effectiveDate') },
    { key: 'extraordinary', label: t('serviceContracts.fields.extraordinary'), type: 'select', default: 'false',
      options: [{ value: 'true', label: t('serviceContracts.yes') }, { value: 'false', label: t('serviceContracts.no') }] },
  ], [t]);

  if (error) return <div className="page"><div role="alert" className="alert alert-error">{error}</div>
    <div className="dossier-navigation">
      <button type="button" className="btn btn-secondary" onClick={reload}>{t('serviceContracts.retry')}</button>
      <Link className="btn btn-secondary" to="/service-contracts">{t('serviceContracts.backToList')}</Link>
    </div></div>;
  if (!contract) return <div className="page-loading" role="status">{t('serviceContracts.loading')}</div>;

  const run = async action => {
    setActionError(null);
    try { await action(); } catch (failure) { setActionError(failure.message); }
  };
  const openEdit = () => { setModal('edit'); api.list('/contacts').then(setContacts).catch(() => setContacts([])); };
  const terms = contract.terms || {};
  const next = contract.next_deadline;
  const tabLabel = key => {
    switch (key) {
      case 'master': return t('serviceContracts.tabs.master');
      case 'locations': return `${t('serviceContracts.tabs.locations')} (${contract.locations.length})`;
      case 'tariffs': return `${t('serviceContracts.tabs.tariffs')} (${contract.tariffs.length})`;
      case 'deadlines': return t('serviceContracts.tabs.deadlines');
      case 'finance': return t('serviceContracts.tabs.finance');
      default: return t('serviceContracts.tabs.documents');
    }
  };

  return (
    <div className="page property-dossier service-contract-dossier">
      <div className="detail-header">
        <Link className="btn btn-sm btn-secondary" to="/service-contracts">← {t('serviceContracts.backToList')}</Link>
        <div className="detail-title">
          <h1>{contract.title}</h1>
          <span className="text-muted">{typeLabel(t, contract.contract_type)} · {contract.provider_name}
            {contract.contract_number ? ` · ${t('serviceContracts.numberShort')} ${contract.contract_number}` : ''}</span>
        </div>
        <span className={`badge ${STATUS_BADGE[contract.status] || 'badge-gray'}`}>{statusLabel(t, contract.status)}</span>
      </div>
      {contract.restricted && <div role="note" className="alert alert-info">{t('serviceContracts.restrictedNote')}</div>}
      {actionError && <div role="alert" className="alert alert-error">{actionError}</div>}

      <div className="stats-grid sc-kpis">
        <div className="stat-card"><div className="stat-label">{t('serviceContracts.fields.nextDeadline')}</div>
          <div className="stat-value sc-kpi-text">{next ? formatDate(next.date) : '—'}</div>
          {next && <div className="text-muted sc-small">{deadlineLabel(t, next.kind)} · {t('serviceContracts.daysLeft', { days: next.days_left })}</div>}</div>
        <div className="stat-card"><div className="stat-label">{t('serviceContracts.fields.advance')}</div>
          <div className="stat-value sc-kpi-text">{contract.current_advance != null ? formatMoney(contract.current_advance) : '—'}</div>
          {contract.current_advance != null && <div className="text-muted sc-small">{intervalLabel(t, contract.current_advance_interval)}</div>}</div>
        <div className="stat-card"><div className="stat-label">{t('serviceContracts.effectiveEnd')}</div>
          <div className="stat-value sc-kpi-text">{formatDate(contract.effective_end, { blank: t('serviceContracts.openEnded') })}</div></div>
        <div className="stat-card"><div className="stat-label">{t('serviceContracts.fields.recoverable')}</div>
          <div className="stat-value sc-kpi-text">{contract.recoverable ? formatPercent(contract.recoverable_percent) : t('serviceContracts.no')}</div></div>
      </div>

      <div className="detail-tabs" role="tablist" aria-label={contract.title}>
        {TAB_KEYS.map(key => (
          <button key={key} type="button" role="tab" id={`sc-tab-${key}`} aria-selected={tab === key}
            aria-controls={`sc-panel-${key}`} className={`detail-tab ${tab === key ? 'active' : ''}`} onClick={() => setTab(key)}>
            {tabLabel(key)}
          </button>
        ))}
      </div>

      <div className="detail-tab-content" role="tabpanel" id={`sc-panel-${tab}`} aria-labelledby={`sc-tab-${tab}`}>
        {tab === 'master' && (
          <div className="detail-overview-grid">
            <div className="panel">
              <div className="panel-header sc-panel-header"><span>{t('serviceContracts.sections.master')}</span>
                {canWrite && <button type="button" className="btn btn-sm btn-secondary" onClick={openEdit}>{t('serviceContracts.edit')}</button>}</div>
              <div className="panel-body">
                <div className="detail-field"><span>{t('serviceContracts.fields.type')}:</span> {typeLabel(t, contract.contract_type)}</div>
                <div className="detail-field"><span>{t('serviceContracts.fields.provider')}:</span> {contract.provider_name}</div>
                {contract.provider && (contract.provider.email || contract.provider.phone) && <div className="detail-field">
                  <span>{t('serviceContracts.contact')}:</span> {[contract.provider.phone, contract.provider.email].filter(Boolean).join(' · ')}</div>}
                <div className="detail-field"><span>{t('serviceContracts.fields.contractNumber')}:</span> {contract.contract_number || '—'}</div>
                <div className="detail-field"><span>{t('serviceContracts.fields.customerNumber')}:</span> {contract.customer_number || '—'}</div>
                <div className="detail-field"><span>{t('serviceContracts.fields.costCategory')}:</span> {contract.cost_category || '—'}</div>
                {contract.notes && <p className="sc-notes">{contract.notes}</p>}
              </div>
            </div>
            <div className="panel">
              <div className="panel-header sc-panel-header"><span>{t('serviceContracts.sections.term')}</span>
                {canWrite && (terms.cancellation
                  ? <button type="button" className="btn btn-sm btn-secondary" onClick={() => run(async () => {
                    if (confirm && !(await confirm(t('serviceContracts.confirmWithdraw')))) return;
                    await api.del(`${path}/cancel`); reload();
                  })}>{t('serviceContracts.withdraw')}</button>
                  : <button type="button" className="btn btn-sm btn-secondary" onClick={() => setModal('cancel')}>{t('serviceContracts.cancel')}</button>)}
              </div>
              <div className="panel-body">
                <div className="detail-field"><span>{t('serviceContracts.fields.start')}:</span> {formatDate(contract.start_date)}</div>
                <div className="detail-field"><span>{t('serviceContracts.firstTermEnd')}:</span> {formatDate(terms.first_term_end)}</div>
                <div className="detail-field"><span>{t('serviceContracts.fields.renewal')}:</span> {renewalLabel(t, contract.renewal_mode)}</div>
                <div className="detail-field"><span>{t('serviceContracts.noticePeriod')}:</span> {terms.notice
                  ? t('serviceContracts.noticeText', { value: terms.notice.value, unit: noticeUnitLabel(t, terms.notice.unit), to: noticeToLabel(t, terms.notice.to) })
                  : t('serviceContracts.noNotice')}</div>
                <div className="detail-field"><span>{t('serviceContracts.fields.reminderDays')}:</span> {contract.reminder_days}</div>
              </div>
            </div>
          </div>
        )}
        {tab === 'locations' && <LocationsTab contract={contract} canWrite={canWrite} onChanged={reload} />}
        {tab === 'tariffs' && <TariffsTab contract={contract} canWrite={canWrite} onChanged={reload} />}
        {tab === 'deadlines' && <DeadlinesTab contract={contract} />}
        {tab === 'finance' && <FinanceTab contract={contract} canWrite={canBook} today={terms.as_of} />}
        {tab === 'documents' && <DocumentsTab contract={contract} canWrite={canWrite} />}
      </div>

      {canWrite && <div className="sc-danger-zone">
        <button type="button" className="btn btn-sm btn-danger" onClick={() => run(async () => {
          if (confirm && !(await confirm(t('serviceContracts.confirmDelete', { name: contract.title })))) return;
          await api.del(path);
          navigate('/service-contracts');
        })}>{t('serviceContracts.delete')}</button>
      </div>}

      {modal === 'edit' && <FormModal title={t('serviceContracts.editContract')} fields={editFields}
        initial={contract} onSave={async values => {
          await api.put(path, { ...contractPayload(values, contract), updated_at: values.updated_at });
          reload();
        }} onClose={() => setModal(null)} />}
      {modal === 'cancel' && <FormModal title={t('serviceContracts.cancel')} fields={cancelFields}
        onSave={async values => {
          const query = values.extraordinary ? '?extraordinary=true' : '';
          await api.post(`${path}/cancel${query}`, { cancelled_on: values.cancelled_on, effective_date: values.effective_date || null });
          reload();
        }} onClose={() => setModal(null)} />}
    </div>
  );
}
