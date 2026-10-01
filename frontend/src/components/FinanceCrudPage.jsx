import { revisionOptions } from '../editRevision';
import { useState } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useDataStore } from '../contexts/DataStoreContext';
import { useConfirm } from './ConfirmDialog';
import DataTable from './DataTable';
import FormModal from './FormModal';
import StatusBadge from './StatusBadge';
import FinanceLoadState from './FinanceLoadState';
import useWriteAccess from '../hooks/useWriteAccess';

/** Scoped CRUD adapter: the caller owns complete primary AND reference lists.
 * Existing non-finance CrudPage/cache consumers are deliberately unchanged.
 */
export default function FinanceCrudPage({ title, endpoint, columns, formFields, listState, relatedKeys = [] }) {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const { data: { items }, loading, error, reload } = listState;
  const [modal, setModal] = useState(null);
  const { canWrite, isAllowed, requireWrite } = useWriteAccess(endpoint, () => setModal(null));
  const [deleteError, setDeleteError] = useState(null);
  const refresh = () => {
    reload();
    store?.invalidateRelated(endpoint.slice(1), ...relatedKeys);
  };
  const save = async data => {
    requireWrite();
    if (modal === 'create') await api.post(endpoint, data);
    else await api.put(`${endpoint}/${modal.id}`, data);
    setModal(null);
    refresh();
  };
  const remove = async row => {
    if (!isAllowed()) return;
    if (!await confirm(`"${row[columns[0]?.key] || row.id}" ${t('modals.confirmDelete.body')}`)) return;
    setDeleteError(null);
    try {
      if (!isAllowed()) return;
      await api.del(`${endpoint}/${row.id}`, revisionOptions(row));
      refresh();
    } catch (err) {
      setDeleteError(err.message);
    }
  };
  if (loading || error) return <FinanceLoadState loading={loading} error={error} onRetry={reload} />;
  return <div className="page">
    {deleteError && <div className="alert alert-error" role="alert">{deleteError}</div>}
    <DataTable
      title={title}
      columns={columns.map(col => ({ ...col, render: col.render || (col.type === 'status' ? value => <StatusBadge status={value} /> : undefined) }))}
      data={items} onAdd={canWrite ? () => setModal('create') : undefined} onEdit={canWrite ? setModal : undefined} onDelete={canWrite ? remove : undefined}
    />
    {modal && canWrite && <FormModal
      title={`${title} ${t(modal === 'create' ? 'ui.buttons.create' : 'ui.buttons.edit').toLowerCase()}`}
      fields={formFields} initial={modal === 'create' ? null : modal}
      onSave={save} onClose={() => setModal(null)}
    />}
  </div>;
}
