import { useState, useEffect } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import { useConfirm } from '../components/ConfirmDialog';

const TYPE_OPTIONS = [
  { value: 'move_in', label: 'Einzug' },
  { value: 'move_out', label: 'Auszug' },
];

const STATUS_OPTIONS = [
  { value: 'draft', label: 'Entwurf' },
  { value: 'signed', label: 'Unterschrieben' },
  { value: 'finalized', label: 'Abgeschlossen' },
];

const CONDITION_OPTIONS = [
  { value: 'good', label: 'Gut' },
  { value: 'fair', label: 'Befriedigend' },
  { value: 'poor', label: 'Mangelhaft' },
];

const TYPE_LABELS = Object.fromEntries(TYPE_OPTIONS.map(o => [o.value, o.label]));
const STATUS_LABELS = Object.fromEntries(STATUS_OPTIONS.map(o => [o.value, o.label]));
const CONDITION_LABELS = Object.fromEntries(CONDITION_OPTIONS.map(o => [o.value, o.label]));

const COLUMNS = [
  { key: 'protocol_date', label: 'Datum', type: 'date' },
  { key: 'protocol_type', label: 'Typ', render: v => TYPE_LABELS[v] || v },
  { key: 'unit_label', label: 'Einheit' },
  { key: 'contract_label', label: 'Vertrag' },
  { key: 'overall_condition', label: 'Zustand', render: v => CONDITION_LABELS[v] || v || '—' },
  { key: 'status', label: 'Status', render: v => STATUS_LABELS[v] || v },
  { key: 'key_count', label: 'Schlüssel', align: 'right' },
];

export default function HandoverProtocols() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const { items: units } = useEntities('units', '/units');
  const { items: contracts } = useEntities('contracts', '/contracts');
  const [protocols, setProtocols] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [modal, setModal] = useState(null);
  const [deleteError, setDeleteError] = useState(null);

  const refreshData = () => {
    setLoading(true);
    api.get('/handover-protocols').catch(err => { console.warn('[HandoverProtocols] protocols:', err.message); return []; })
      .then(p => setProtocols(p || []))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    let cancelled = false;
    api.get('/handover-protocols').catch(err => { console.warn('[HandoverProtocols] protocols:', err.message); return []; })
      .then(data => { if (!cancelled) setProtocols(data || []); })
      .catch(e => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const unitMap = Object.fromEntries(units.map(u => [u.id, u.name]));
  const contractMap = Object.fromEntries(contracts.map(c => [c.id, c.contract_number || c.id]));

  const enriched = protocols.map(p => ({
    ...p,
    unit_label: unitMap[p.unit_id] || '—',
    contract_label: contractMap[p.contract_id] || '—',
  }));

  const fields = [
    { key: 'contract_id', label: 'Vertrag', type: 'select', required: true,
      options: contracts.map(c => ({ value: c.id, label: c.contract_number || c.id })) },
    { key: 'unit_id', label: 'Einheit', type: 'select', required: true,
      options: units.map(u => ({ value: u.id, label: u.name })) },
    { key: 'protocol_type', label: 'Typ', type: 'select', required: true, options: TYPE_OPTIONS },
    { key: 'protocol_date', label: 'Datum', type: 'date', required: true },
    { key: 'status', label: 'Status', type: 'select', options: STATUS_OPTIONS },
    { key: 'overall_condition', label: 'Gesamtzustand', type: 'select', options: CONDITION_OPTIONS },
    { key: 'tenant_present', label: 'Mieter anwesend', type: 'select', options: [
      { value: 'true', label: 'Ja' }, { value: 'false', label: 'Nein' },
    ]},
    { key: 'landlord_present', label: 'Vermieter anwesend', type: 'select', options: [
      { value: 'true', label: 'Ja' }, { value: 'false', label: 'Nein' },
    ]},
    { key: 'key_count', label: 'Anzahl Schlüssel', type: 'number' },
    { key: 'key_details', label: 'Schlüsseldetails' },
    { key: 'damages', label: 'Mängel', type: 'textarea', placeholder: 'Beschreibung der Mängel' },
    { key: 'notes', label: 'Bemerkungen', type: 'textarea' },
  ];

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/handover-protocols', data);
    } else {
      await api.put(`/handover-protocols/${modal.id}`, data);
    }
    refreshData();
    if (store) store.invalidateRelated('handover_protocols', 'contracts', 'units');
  };

  const handleDelete = async (row) => {
    const name = `${TYPE_LABELS[row.protocol_type] || row.protocol_type} ${row.protocol_date || ''}`;
    if (!await confirm(`"${name}" ${t('modals.confirmDelete.body')}`)) return;
    setDeleteError(null);
    try {
      await api.del(`/handover-protocols/${row.id}`);
      refreshData();
      if (store) store.invalidateRelated('handover_protocols', 'contracts', 'units');
    } catch (err) {
      setDeleteError(err.message || 'Löschen fehlgeschlagen');
    }
  };

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
        title="Übergabeprotokolle"
        columns={COLUMNS}
        data={enriched}
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
      />
      {modal && (
        <FormModal
          title={modal === 'create' ? 'Übergabeprotokoll erstellen' : 'Übergabeprotokoll bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
