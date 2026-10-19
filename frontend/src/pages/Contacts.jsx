import { useState, useEffect, useCallback } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { useTranslation } from '../i18n';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import { SearchIcon } from '../components/Icons';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';
import { bulkDelete } from '../utils/bulkActions';

const COLUMNS = [
  { key: 'display_name', label: 'Name', filterType: 'text' },
  { key: 'contact_type', label: 'Rolle', filterType: 'select',
    render: v => {
      const labels = { tenant: 'Mieter', owner: 'Eigentümer', supplier: 'Dienstleister', manager: 'Verwalter' };
      return <StatusBadge status={v} label={labels[v] || v} />;
    }},
  { key: 'email', label: 'E-Mail', filterType: 'text' },
  { key: 'phone', label: 'Telefon' },
  { key: 'city', label: 'Stadt', filterType: 'text' },
  { key: 'company_name', label: 'Firma', filterType: 'text' },
];

const FIELDS = [
  { key: 'contact_type', label: 'Rolle', type: 'select', required: true, default: 'tenant', options: [
    { value: 'tenant', label: 'Mieter' },
    { value: 'owner', label: 'Eigentümer' },
    { value: 'supplier', label: 'Dienstleister' },
    { value: 'manager', label: 'Verwalter' },
  ]},
  { key: 'first_name', label: 'Vorname' },
  { key: 'last_name', label: 'Nachname' },
  { key: 'company_name', label: 'Firma' },
  { key: 'email', label: 'E-Mail', type: 'email' },
  { key: 'phone', label: 'Telefon' },
  { key: 'mobile', label: 'Mobil' },
  { key: 'street', label: 'Straße' },
  { key: 'zip_code', label: 'PLZ' },
  { key: 'city', label: 'Stadt' },
  { key: 'iban', label: 'IBAN' },
  { key: 'bank_name', label: 'Bank' },
  { key: 'tax_id', label: 'Steuer-Nr.' },
  { key: 'notes', label: 'Notizen', type: 'textarea' },
];

export default function Contacts() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [contacts, setContacts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [tab, setTab] = useState('all');
  const [loadError, setLoadError] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [revision, setRevision] = useState(0);

  const loadData = useCallback(() => setRevision(value => value + 1), []);
  useEffect(() => {
    const request = new AbortController();
    setLoading(true);
    api.list('/contacts', { signal: request.signal }).then(data => {
      if (request.signal.aborted) return;
      if (!Array.isArray(data)) throw new Error('Kontakte konnten nicht vollständig gelesen werden.');
      // Add display_name for each contact
      const enriched = data.map(c => ({
        ...c,
        display_name: c.company_name || [c.first_name, c.last_name].filter(Boolean).join(' ') || 'Unbenannt',
      }));
      setContacts(enriched); setLoaded(true); setLoadError(null);
    }).catch(error => { if (!request.signal.aborted) setLoadError(error.message || 'Kontakte konnten nicht geladen werden.'); })
      .finally(() => { if (!request.signal.aborted) setLoading(false); });
    return () => request.abort();
  }, [revision]);

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/contacts', data);
    } else {
      await api.put(`/contacts/${modal.id}`, data);
    }
    loadData();
  };

  const handleDelete = async (row) => {
    if (!await confirm(`"${row.display_name}" ${t('modals.confirmDelete.body')}`)) return;
    await api.del(`/contacts/${row.id}`);
    loadData();
  };

  const activeTab = params.get('focus_id') || params.get('suche') ? 'all' : tab;
  const filtered = activeTab === 'all' ? contacts : contacts.filter(c => c.contact_type === activeTab);
  const chooseTab = value => {
    setTab(value);
    setParams(current => { const next = new URLSearchParams(current); next.delete('focus_id'); next.delete('suche'); return next; });
  };

  const counts = {
    all: contacts.length,
    tenant: contacts.filter(c => c.contact_type === 'tenant').length,
    owner: contacts.filter(c => c.contact_type === 'owner').length,
    supplier: contacts.filter(c => c.contact_type === 'supplier').length,
    manager: contacts.filter(c => c.contact_type === 'manager').length,
  };

  if (loading && !loaded && !modal) return <div className="page-loading">Laden...</div>;
  if (loadError && !loaded && !modal) return <div className="page"><p className="alert-error" role="alert">{loadError}{' '}
    <button type="button" className="btn btn-secondary btn-sm" onClick={loadData}>Erneut laden</button></p></div>;

  return (
    <div className="page">
      {loadError && <p className="alert-error" role="alert">Kontakte konnten nicht aktualisiert werden. {loadError} Angezeigt wird der zuletzt geladene Stand.{' '}
        <button type="button" className="btn btn-secondary btn-sm" onClick={loadData}>Erneut laden</button></p>}
      <div className="tab-bar" style={{ marginBottom: '1rem' }}>
        {[
          { key: 'all', label: 'Alle' },
          { key: 'tenant', label: 'Mieter' },
          { key: 'owner', label: 'Eigentümer' },
          { key: 'supplier', label: 'Dienstleister' },
          { key: 'manager', label: 'Verwalter' },
        ].map(t => (
          <button
            key={t.key}
            className={`detail-tab ${activeTab === t.key ? 'active' : ''}`}
            onClick={() => chooseTab(t.key)}
          >
            {t.label} ({counts[t.key]})
          </button>
        ))}
      </div>
      <DataTable
        title="Kontakte"
        columns={COLUMNS}
        data={filtered}
        rowName={row => row.display_name || row.id}
        bulkActions={[bulkDelete({ one: 'Kontakt', many: 'Kontakte', remove: row => api.del(`/contacts/${row.id}`),
          finished: () => loadData() })]}
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
        rowActions={() => [{ label: 'Dubletten prüfen', icon: <SearchIcon size={14} />, onClick: row => navigate(`/duplicate-check?kind=contact&id=${encodeURIComponent(row.id)}`) }]}
      />
      {modal && (
        <FormModal
          title={modal === 'create' ? 'Kontakt erstellen' : 'Kontakt bearbeiten'}
          repeatKeep={['contact_type']}
          fields={FIELDS}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
