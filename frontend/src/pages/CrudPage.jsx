import { useState } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import { useConfirm } from '../components/ConfirmDialog';

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

export default function CrudPage({ title, endpoint, columns, formFields, onRowClick }) {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const eKey = endpointKey(endpoint);
  const { items, loading, error, reload } = useEntities(eKey, endpoint);
  const [modal, setModal] = useState(null); // null | 'create' | item
  const [deleteError, setDeleteError] = useState(null);

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

  if (loading) return <div className="page-loading">{t('ui.table.loading')}</div>;
  if (error) return <div className="page"><div className="alert alert-error">{error}</div></div>;

  return (
    <div className="page">
      {deleteError && (
        <div className="alert alert-error" style={{ marginBottom: '1rem' }}>
          {deleteError}
          <button onClick={() => setDeleteError(null)} style={{ marginLeft: '1rem', cursor: 'pointer' }}>✕</button>
        </div>
      )}
      <DataTable
        title={title}
        columns={tableColumns}
        data={items}
        onAdd={() => setModal('create')}
        onEdit={(row) => setModal(row)}
        onDelete={handleDelete}
        onRowClick={onRowClick}
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
