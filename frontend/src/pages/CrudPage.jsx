import { useState } from 'react';
import { api } from '../api';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useList } from '../hooks/useApi';

export default function CrudPage({ title, endpoint, columns, formFields }) {
  const { items, loading, error, reload } = useList(endpoint);
  const [modal, setModal] = useState(null); // null | 'create' | item

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post(endpoint, data);
    } else {
      await api.put(`${endpoint}/${modal.id}`, data);
    }
    reload();
  };

  const handleDelete = async (row) => {
    if (!window.confirm(`"${row[columns[0]?.key] || row.id}" wirklich löschen?`)) return;
    await api.del(`${endpoint}/${row.id}`);
    reload();
  };

  const tableColumns = columns.map(col => ({
    ...col,
    render: col.render || (col.type === 'status'
      ? (val) => <StatusBadge status={val} />
      : undefined),
  }));

  if (loading) return <div className="page-loading">Laden...</div>;
  if (error) return <div className="page"><div className="alert alert-error">{error}</div></div>;

  return (
    <div className="page">
      <DataTable
        title={title}
        columns={tableColumns}
        data={items}
        onAdd={() => setModal('create')}
        onEdit={(row) => setModal(row)}
        onDelete={handleDelete}
      />
      {modal && (
        <FormModal
          title={modal === 'create' ? `${title} erstellen` : `${title} bearbeiten`}
          fields={formFields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
