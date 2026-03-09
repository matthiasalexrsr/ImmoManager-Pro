import { useState, useEffect } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';

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
  const [contacts, setContacts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [tab, setTab] = useState('all');

  const loadData = () => {
    api.get('/contacts').then(data => {
      // Add display_name for each contact
      const enriched = (data || []).map(c => ({
        ...c,
        display_name: c.company_name || [c.first_name, c.last_name].filter(Boolean).join(' ') || 'Unbenannt',
      }));
      setContacts(enriched);
    }).catch(() => setContacts([])).finally(() => setLoading(false));
  };

  useEffect(() => { loadData(); }, []);

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/contacts', data);
    } else {
      await api.put(`/contacts/${modal.id}`, data);
    }
    loadData();
  };

  const handleDelete = async (row) => {
    if (!window.confirm(`"${row.display_name}" ${t('modals.confirmDelete.body')}`)) return;
    await api.del(`/contacts/${row.id}`);
    loadData();
  };

  const filtered = tab === 'all' ? contacts : contacts.filter(c => c.contact_type === tab);

  const counts = {
    all: contacts.length,
    tenant: contacts.filter(c => c.contact_type === 'tenant').length,
    owner: contacts.filter(c => c.contact_type === 'owner').length,
    supplier: contacts.filter(c => c.contact_type === 'supplier').length,
    manager: contacts.filter(c => c.contact_type === 'manager').length,
  };

  if (loading) return <div className="page-loading">Laden...</div>;

  return (
    <div className="page">
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
            className={`detail-tab ${tab === t.key ? 'active' : ''}`}
            onClick={() => setTab(t.key)}
          >
            {t.label} ({counts[t.key]})
          </button>
        ))}
      </div>
      <DataTable
        title="Kontakte"
        columns={COLUMNS}
        data={filtered}
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
      />
      {modal && (
        <FormModal
          title={modal === 'create' ? 'Kontakt erstellen' : 'Kontakt bearbeiten'}
          fields={FIELDS}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
