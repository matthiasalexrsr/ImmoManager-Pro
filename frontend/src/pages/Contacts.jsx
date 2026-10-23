import { useState, useEffect, useCallback } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { useTranslation } from '../i18n';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import { SearchIcon } from '../components/Icons';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';
import { bulkDelete } from '../utils/bulkActions';
import { formatDate } from '../utils/format';

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

// An owner's shares with their property and unit (backend: /ownership-shares/holdings), and where their money is.
function OwnerHoldings({ owner, onClose }) {
  const [state, setState] = useState({ status: 'loading', data: null, error: '' });
  useEffect(() => {
    let active = true;
    api.get(`/ownership-shares/holdings?owner_contact_id=${encodeURIComponent(owner.id)}`)
      .then(data => { if (active) setState({ status: 'ready', data, error: '' }); })
      .catch(error => { if (active) setState({ status: 'error', data: null, error: error.message || 'Die Anteile konnten nicht geladen werden.' }); });
    return () => { active = false; };
  }, [owner.id]);
  const percent = value => `${Number(value).toLocaleString('de-DE', { maximumFractionDigits: 4 })} %`;
  return <section className="panel" aria-label={`Anteile von ${owner.display_name}`} style={{ marginTop: '1rem' }}>
    <div className="panel-header">Anteile von {owner.display_name}</div>
    <div className="panel-body">
      {state.status === 'loading' && <p role="status">Anteile werden geladen …</p>}
      {state.status === 'error' && <p className="alert-error" role="alert">{state.error}</p>}
      {state.status === 'ready' && (state.data.shares.length === 0
        ? <p>Für diesen Eigentümer ist noch kein Anteil erfasst. Anteile werden am Objekt im Bereich „Eigentümer“ erfasst.</p>
        : <div className="dossier-table-scroll"><table className="data-table">
          <caption className="sr-only">Eigentumsanteile</caption>
          <thead><tr><th scope="col">Objekt</th><th scope="col">Einheit</th><th scope="col" className="text-right">Anteil</th>
            <th scope="col">Gültig ab</th><th scope="col">Gültig bis</th><th scope="col">Stand</th></tr></thead>
          <tbody>{state.data.shares.map(share => <tr key={share.id}>
            <th scope="row"><Link to={`/properties/${encodeURIComponent(share.property_id)}?tab=owners`}>{share.property_name || 'Objekt'}</Link></th>
            <td>{share.unit_id ? <Link to={`/units/${encodeURIComponent(share.unit_id)}`}>{share.unit_label || 'Einheit'}</Link> : 'ganzes Objekt'}</td>
            <td className="text-right">{percent(share.share_percent)}</td>
            <td>{share.valid_from ? formatDate(share.valid_from) : 'seit jeher'}</td>
            <td>{share.valid_to ? formatDate(share.valid_to) : 'offen'}</td>
            <td>{share.current ? 'aktuell' : 'nicht aktuell'}</td></tr>)}</tbody></table></div>)}
      <p><Link to={`/bookings?owner_contact_id=${encodeURIComponent(owner.id)}`}>Buchungen mit Anteil dieses Eigentümers</Link>{' · '}
        <Link to="/reports">Ergebnis je Eigentümer in den Berichten</Link></p>
      <button type="button" className="btn btn-secondary btn-sm" onClick={onClose}>Schließen</button>
    </div>
  </section>;
}

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
  const [holdings, setHoldings] = useState(null);

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
    if (!await confirm(`"${row.display_name}" ${t('modals.confirmDelete.body')}`, { action: 'delete' })) return;
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
        rowActions={row => [
          ...(row.contact_type === 'owner' ? [{ label: 'Anteile anzeigen', onClick: owner => setHoldings(owner) }] : []),
          { label: 'Dubletten prüfen', icon: <SearchIcon size={14} />, onClick: row => navigate(`/duplicate-check?kind=contact&id=${encodeURIComponent(row.id)}`) }]}
      />
      {holdings && <OwnerHoldings key={holdings.id} owner={holdings} onClose={() => setHoldings(null)} />}
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
