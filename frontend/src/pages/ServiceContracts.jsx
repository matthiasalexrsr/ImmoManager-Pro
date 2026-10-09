import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useCanWrite } from '../contexts/AuthContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import { formatDate, formatMoney } from '../utils/format';
import {
  CONTRACT_TYPES, STATUS_BADGE, contractFields, createPayload, deadlineLabel, intervalLabel, statusLabel, typeLabel,
} from '../features/serviceContracts/model';
import '../features/serviceContracts/serviceContracts.css';

// Objektverträge: energy and service contracts of the properties, with their next deadline.
export default function ServiceContracts() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const canWrite = useCanWrite('/service-contracts');
  const [rows, setRows] = useState([]);
  const [deadlines, setDeadlines] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filters, setFilters] = useState({ q: '', contract_type: '', status: '' });
  const [creating, setCreating] = useState(false);
  const [choices, setChoices] = useState({ contacts: [], properties: [], units: [], meters: [] });
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const query = new URLSearchParams(Object.entries(filters).filter(([, v]) => v));
    setLoading(true);
    setError(null);
    Promise.all([
      api.list(`/service-contracts${query.size ? `?${query}` : ''}`, { signal: controller.signal }),
      api.get('/service-contracts/deadlines?days=90', { signal: controller.signal }),
    ]).then(([list, upcoming]) => {
      setRows(list || []);
      setDeadlines(upcoming || []);
    }).catch(failure => {
      if (failure.name !== 'AbortError') setError(failure.message || t('serviceContracts.loadError'));
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [filters, revision, t]);

  const openCreate = useCallback(() => {
    setCreating(true);
    Promise.all(['/contacts', '/properties', '/units', '/meters'].map(path => api.list(path).catch(() => [])))
      .then(([contacts, properties, units, meters]) => setChoices({ contacts, properties, units, meters }));
  }, []);

  const fields = useMemo(() => contractFields(t, { ...choices, withLocation: true }), [t, choices]);

  const save = async values => {
    const created = await api.post('/service-contracts', createPayload(values));
    setRevision(value => value + 1);
    navigate(`/service-contracts/${encodeURIComponent(created.id)}`);
  };

  const columns = [
    { key: 'title', label: t('serviceContracts.fields.title'), filterType: 'text', wrap: true,
      render: (value, row) => <Link to={`/service-contracts/${encodeURIComponent(row.id)}`}>{value}</Link> },
    { key: 'contract_type', label: t('serviceContracts.fields.type'), render: value => typeLabel(t, value) },
    { key: 'provider_name', label: t('serviceContracts.fields.provider'), filterType: 'text' },
    { key: 'locations', label: t('serviceContracts.tabs.locations'), wrap: true,
      render: value => (value || []).map(loc => loc.label).join('; ') || '—' },
    { key: 'status', label: t('serviceContracts.fields.status'),
      render: value => <span className={`badge ${STATUS_BADGE[value] || 'badge-gray'}`}>{statusLabel(t, value)}</span> },
    { key: 'next_deadline', label: t('serviceContracts.fields.nextDeadline'),
      render: value => (value ? `${deadlineLabel(t, value.kind)}: ${formatDate(value.date)}` : '—') },
    { key: 'current_advance', label: t('serviceContracts.fields.advance'), align: 'right',
      render: (value, row) => (value != null ? `${formatMoney(value)} ${intervalLabel(t, row.current_advance_interval)}` : '—') },
  ];

  return (
    <div className="page service-contracts">
      <p className="text-muted service-contracts-intro">{t('serviceContracts.intro')}</p>
      <div className="service-contracts-filters" role="search">
        <input type="search" aria-label={t('serviceContracts.search')} placeholder={t('serviceContracts.search')}
          value={filters.q} onChange={e => setFilters(f => ({ ...f, q: e.target.value }))} />
        <select aria-label={t('serviceContracts.fields.type')} value={filters.contract_type}
          onChange={e => setFilters(f => ({ ...f, contract_type: e.target.value }))}>
          <option value="">{t('serviceContracts.allTypes')}</option>
          {CONTRACT_TYPES.map(type => <option key={type} value={type}>{typeLabel(t, type)}</option>)}
        </select>
        <select aria-label={t('serviceContracts.fields.status')} value={filters.status}
          onChange={e => setFilters(f => ({ ...f, status: e.target.value }))}>
          <option value="">{t('serviceContracts.allStatuses')}</option>
          {['active', 'cancelled', 'upcoming', 'ended'].map(s => <option key={s} value={s}>{statusLabel(t, s)}</option>)}
        </select>
      </div>
      {error && <div role="alert" className="alert alert-error">{error}
        <button type="button" className="btn btn-sm btn-secondary" onClick={() => setRevision(v => v + 1)}>
          {t('serviceContracts.retry')}</button></div>}
      <section className="panel service-contracts-deadlines" aria-labelledby="sc-deadlines-title">
        <div className="panel-header" id="sc-deadlines-title">{t('serviceContracts.upcomingTitle')}</div>
        <div className="panel-body">
          {deadlines.length === 0 ? <p className="empty-text">{t('serviceContracts.noUpcoming')}</p> : (
            <ul className="service-contracts-deadline-list">
              {deadlines.map(d => (
                <li key={`${d.service_contract_id}-${d.kind}-${d.date}`} className={d.days_left <= 14 ? 'is-urgent' : ''}>
                  <span className="sc-deadline-date">{formatDate(d.date)}</span>
                  <span>{deadlineLabel(t, d.kind)}</span>
                  <Link to={`/service-contracts/${encodeURIComponent(d.service_contract_id)}`}>{d.title}</Link>
                  <span className="text-muted">{t('serviceContracts.daysLeft', { days: d.days_left })}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
      {loading ? <div className="page-loading" role="status">{t('serviceContracts.loading')}</div> : (
        <DataTable title={t('serviceContracts.title')} columns={columns} data={rows} writeArea="/service-contracts"
          onAdd={canWrite ? openCreate : undefined} />
      )}
      {creating && <FormModal title={t('serviceContracts.create')} fields={fields} onSave={save}
        onClose={() => setCreating(false)} />}
    </div>
  );
}
