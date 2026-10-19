import { useState } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import { useConfirm } from '../components/ConfirmDialog';
import { bulkDelete } from '../utils/bulkActions';

// Derive a cache key from endpoint, e.g. "/properties" → "properties"
function endpointKey(ep) {
  return ep.replace(/^\//, '').replace(/\//g, '_');
}

// Relationship map: when entity X changes, also refresh these related entities.
// This enables targeted invalidation instead of refetching every cached entity.
const _RELATED_ENTITIES = {
  properties: ['portfolios', 'units', 'contracts'],
  units: ['properties', 'contracts', 'listings', 'meters'],
  tenants: ['contracts'],
  contracts: ['properties', 'units', 'tenants', 'deposits', 'receivables', 'rent_adjustments'],
  accounts: ['portfolios', 'bookings'],
  bookings: ['accounts', 'receivables'],
  invoices: ['contracts', 'receivables'],
  deposits: ['contracts'],
  receivables: ['contracts', 'bookings'],
  maintenance: ['properties', 'units'],
  insurances: ['properties'],
  rent_adjustments: ['contracts'],
  rent_charges: ['contracts'],
  listings: ['units'],
  categories: ['bookings'],
};

export default function CrudPage({ title, endpoint, columns, formFields, onRowClick, enrichRow, formAvailability }) {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const eKey = endpointKey(endpoint);
  const { items, loading, error, reload } = useEntities(eKey, endpoint);
  const [modal, setModal] = useState(null); // null | 'create' | item
  const [deleteError, setDeleteError] = useState(null);
  const formReady = !formAvailability?.loading && !formAvailability?.error;
  const openForm = value => { if (formReady) setModal(value); };

  const invalidateAfterMutation = () => {
    if (!store) { reload(); return; }
    const related = _RELATED_ENTITIES[eKey] || [];
    store.invalidateRelated(eKey, ...related);
  };

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post(endpoint, data);
    } else {
      await api.put(`${endpoint}/${modal.id}`, data);
    }
    invalidateAfterMutation();
  };

  const handleDelete = async (row) => {
    const name = row[columns[0]?.key] || row.id;
    if (!await confirm(`"${name}" ${t('modals.confirmDelete.body')}`)) return;
    setDeleteError(null);
    try {
      await api.del(`${endpoint}/${row.id}`);
      invalidateAfterMutation();
    } catch (err) {
      setDeleteError(err.message || 'Löschen fehlgeschlagen');
    }
  };

  const tableColumns = columns.map(col => ({
    ...col,
    render: col.render || (col.type === 'status'
      ? (val) => <StatusBadge status={val} />
      : undefined),
  }));

  // only the first load replaces the list; a reload keeps the table (its search, selection, results)
  // An open form owns draft cleanup and closing after its mutation triggers a reload.
  if (loading && items.length === 0 && !modal) return <div className="page-loading">{t('ui.table.loading')}</div>;
  if (error && !modal && items.length === 0) return <div className="page"><div role="alert" className="alert alert-error">{error}</div><button type="button" className="btn btn-secondary" onClick={reload}>Erneut laden</button></div>;

  return (
    <div className="page">
      {error && <div role="alert" className="alert alert-error">{error} Die letzte erfolgreich geladene Ansicht bleibt sichtbar. <button type="button" onClick={reload}>Erneut laden</button></div>}
      {formAvailability?.loading && <p role="status">Die Auswahl für das Bearbeitungsformular wird geladen…</p>}
      {formAvailability?.error && <div role="alert" className="alert alert-error">{formAvailability.error} Das Bearbeitungsformular ist erst nach erfolgreichem Laden verfügbar. <button type="button" onClick={formAvailability.retry}>Auswahl erneut laden</button></div>}
      {deleteError && (
        <div className="alert alert-error" role="alert" style={{ marginBottom: '1rem' }}>
          {deleteError}
          <button type="button" onClick={() => setDeleteError(null)} aria-label="Meldung schließen" style={{ marginLeft: '1rem', cursor: 'pointer' }}>✕</button>
        </div>
      )}
      <DataTable
        title={title}
        columns={tableColumns}
        data={enrichRow ? items.map(enrichRow) : items}
        onAdd={() => openForm('create')}
        onEdit={openForm}
        onDelete={handleDelete}
        onRowClick={onRowClick}
        bulkActions={[bulkDelete({ one: 'Eintrag', many: 'Einträge', remove: row => api.del(`${endpoint}/${row.id}`),
          finished: invalidateAfterMutation })]}
      />
      {modal && (
        <FormModal
          title={modal === 'create' ? `${title} ${t('ui.buttons.create').toLowerCase()}` : `${title} ${t('ui.buttons.edit').toLowerCase()}`}
          fields={formFields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
