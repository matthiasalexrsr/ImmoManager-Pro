import { useState, useEffect } from 'react';
import { api } from '../api';
import DataTable from '../components/DataTable';

const COLUMNS = [
  { key: 'full_name', label: 'Name', filterType: 'text' },
  { key: 'role', label: 'Rolle', filterType: 'select' },
  { key: 'email', label: 'E-Mail', filterType: 'text' },
  { key: 'phone', label: 'Telefon' },
  { key: 'company', label: 'Firma', filterType: 'text' },
  { key: 'linked_properties', label: 'Immobilien', type: 'number' },
];

export default function Contacts() {
  const [contacts, setContacts] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.get('/tenants').catch(() => []),
      api.get('/contracts').catch(() => []),
    ]).then(([tenants, contracts]) => {
      // Build contact list from tenants with roles
      const tenantContracts = {};
      contracts.forEach(c => {
        if (!tenantContracts[c.tenant_id]) tenantContracts[c.tenant_id] = [];
        tenantContracts[c.tenant_id].push(c);
      });

      const contactList = tenants.map(t => ({
        ...t,
        role: tenantContracts[t.id]?.some(c => c.status === 'active') ? 'Mieter (aktiv)' : 'Mieter',
        linked_properties: tenantContracts[t.id]?.length || 0,
      }));
      setContacts(contactList);
    }).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="page-loading">Laden...</div>;

  return (
    <div className="page">
      <DataTable title="Kontakte" columns={COLUMNS} data={contacts} />
    </div>
  );
}
