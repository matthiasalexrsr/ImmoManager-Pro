import { useState, useEffect } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import { useConfirm } from '../components/ConfirmDialog';

const COLUMNS = [
  { key: 'full_name', label: 'Name', filterType: 'text' },
  { key: 'email', label: 'E-Mail', filterType: 'text' },
  { key: 'phone', label: 'Telefon' },
  { key: 'city', label: 'Stadt', filterType: 'text' },
  { key: 'payment_method', label: 'Zahlungsart', filterType: 'select',
    render: v => {
      const labels = { bank_transfer: 'Überweisung', sepa_direct_debit: 'SEPA-Lastschrift', cash: 'Bar' };
      return labels[v] || v || '—';
    }},
];

const FIELDS = [
  { key: 'full_name', label: 'Vollständiger Name', required: true },
  { key: 'email', label: 'E-Mail', type: 'email' },
  { key: 'phone', label: 'Telefon' },
  { key: 'address_line', label: 'Straße' },
  { key: 'postal_code', label: 'PLZ' },
  { key: 'city', label: 'Stadt' },
  { key: 'country', label: 'Land', default: 'DE' },
  { key: 'payment_method', label: 'Zahlungsart', type: 'select', options: [
    { value: 'bank_transfer', label: 'Überweisung' },
    { value: 'sepa_direct_debit', label: 'SEPA-Lastschrift' },
    { value: 'cash', label: 'Bar' },
  ]},
  { key: 'sepa_mandate', label: 'SEPA-Mandat', placeholder: 'Mandatsreferenz' },
  { key: 'notes', label: 'Notizen', type: 'textarea' },
];

export default function Tenants() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const [tenants, setTenants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [error, setError] = useState(null);
  const [showArchived, setShowArchived] = useState(false);

  const refreshData = () => {
    setLoading(true);
    api.get('/tenants?include_archived=true')
      .then(data => setTenants(data || []))
      .catch(() => setTenants([]))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    let cancelled = false;
    api.get('/tenants?include_archived=true')
      .then(data => {
        if (!cancelled) setTenants(data || []);
      })
      .catch(() => {
        if (!cancelled) setTenants([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const activeTenants = tenants.filter(t => !t.archived);
  const archivedTenants = tenants.filter(t => t.archived);

  // Invalidate global cache so other pages see updated tenant data
  const afterMutation = () => {
    refreshData();
    if (store) store.invalidateRelated('tenants', 'contracts');
  };

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/tenants', data);
    } else {
      await api.put(`/tenants/${modal.id}`, data);
    }
    afterMutation();
  };

  const handleDelete = async (row) => {
    const name = row.full_name || row.id;
    if (!await confirm(`"${name}" ${t('modals.confirmDelete.body')}`)) return;
    setError(null);
    try {
      await api.del(`/tenants/${row.id}`);
      afterMutation();
    } catch (err) {
      setError(err.message || 'Löschen fehlgeschlagen');
    }
  };

  const handleArchive = async (tenant) => {
    if (!await confirm(`"${tenant.full_name}" ${t('pages.tenants.archiveConfirm') || 'archivieren? Der Mieter wird aus der aktiven Liste entfernt.'}`)) return;
    try {
      await api.patch(`/tenants/${tenant.id}/archive`, {});
      afterMutation();
    } catch (err) {
      setError(err.message || 'Archivierung fehlgeschlagen');
    }
  };

  const handleUnarchive = async (tenant) => {
    try {
      await api.patch(`/tenants/${tenant.id}/unarchive`, {});
      afterMutation();
    } catch (err) {
      setError(err.message || 'Wiederherstellung fehlgeschlagen');
    }
  };

  if (loading) return <div className="page-loading">{t('ui.table.loading')}</div>;

  return (
    <div className="page">
      {error && (
        <div className="alert alert-error" style={{ marginBottom: '1rem' }}>
          {error}
          <button onClick={() => setError(null)} style={{ marginLeft: '1rem', cursor: 'pointer' }}>✕</button>
        </div>
      )}

      {/* Active Tenants */}
      <DataTable
        title={`Mieter (${activeTenants.length})`}
        columns={COLUMNS}
        data={activeTenants}
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
      />

      {/* Archive actions for active tenants */}
      {activeTenants.length > 0 && (
        <div style={{ marginTop: '0.5rem', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
          Mieter archivieren:{' '}
          {activeTenants.map((t, i) => (
            <span key={t.id}>
              {i > 0 && ', '}
              <button
                onClick={() => handleArchive(t)}
                style={{
                  background: 'none', border: 'none', color: 'var(--primary)',
                  cursor: 'pointer', textDecoration: 'underline', padding: 0,
                  fontSize: 'inherit',
                }}
              >
                {t.full_name}
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Archived section */}
      <div style={{ marginTop: '2rem', borderTop: '1px solid var(--border-color, #e2e8f0)', paddingTop: '1rem' }}>
        <button
          className={`btn btn-sm ${showArchived ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setShowArchived(!showArchived)}
        >
          {showArchived ? 'Archiv ausblenden' : `Archiv anzeigen${archivedTenants.length > 0 ? ` (${archivedTenants.length})` : ''}`}
        </button>

        {showArchived && (
          <div style={{ marginTop: '1rem' }}>
            {archivedTenants.length === 0 ? (
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                Keine archivierten Mieter vorhanden.
              </p>
            ) : (
              <>
                <DataTable
                  title={`Archivierte Mieter (${archivedTenants.length})`}
                  columns={COLUMNS}
                  data={archivedTenants}
                  onEdit={row => setModal(row)}
                />
                <div style={{ marginTop: '0.5rem', display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                  {archivedTenants.map(t => (
                    <button
                      key={t.id}
                      className="btn btn-sm btn-secondary"
                      onClick={() => handleUnarchive(t)}
                    >
                      {t.full_name} wiederherstellen
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {modal && (
        <FormModal
          title={modal === 'create' ? 'Mieter erstellen' : 'Mieter bearbeiten'}
          fields={FIELDS}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
