import { useState, useEffect } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';

const PORTAL_TEMPLATES = {
  immoscout24: {
    label: 'ImmoScout24',
    format: (listing, unit) => [
      `🏠 ${listing.title}`,
      '',
      unit?.area_sqm ? `Wohnfläche: ${unit.area_sqm} m²` : '',
      unit?.rooms ? `Zimmer: ${unit.rooms}` : '',
      unit?.floor ? `Etage: ${unit.floor}` : '',
      listing.target_rent ? `Kaltmiete: ${Number(listing.target_rent).toFixed(2)} €` : '',
      listing.service_charge ? `Nebenkosten: ${Number(listing.service_charge).toFixed(2)} €` : '',
      listing.target_rent && listing.service_charge
        ? `Warmmiete: ${(Number(listing.target_rent) + Number(listing.service_charge)).toFixed(2)} €`
        : '',
      '',
      listing.available_from ? `Verfügbar ab: ${listing.available_from}` : '',
      '',
      unit?.features ? `Ausstattung: ${unit.features}` : '',
      '',
      listing.description || '',
      '',
      listing.contact_name ? `Ansprechpartner: ${listing.contact_name}` : '',
      listing.contact_email ? `Kontakt: ${listing.contact_email}` : '',
    ].filter(Boolean).join('\n'),
  },
  immowelt: {
    label: 'Immowelt',
    format: (listing, unit) => [
      listing.title,
      '---',
      unit?.area_sqm ? `Fläche: ${unit.area_sqm} m²` : '',
      unit?.rooms ? `Zimmer: ${unit.rooms}` : '',
      listing.target_rent ? `Miete: ${Number(listing.target_rent).toFixed(2)} € (kalt)` : '',
      listing.service_charge ? `NK: ${Number(listing.service_charge).toFixed(2)} €` : '',
      listing.available_from ? `Ab: ${listing.available_from}` : '',
      '---',
      listing.description || '',
    ].filter(Boolean).join('\n'),
  },
  ebay: {
    label: 'eBay Kleinanzeigen',
    format: (listing, unit) => [
      listing.title,
      '',
      listing.target_rent ? `Miete: ${Number(listing.target_rent).toFixed(2)} € kalt` : '',
      unit?.area_sqm ? `${unit.area_sqm} m²` : '',
      unit?.rooms ? `${unit.rooms} Zimmer` : '',
      listing.available_from ? `Frei ab ${listing.available_from}` : '',
      '',
      listing.description || '',
      '',
      listing.contact_name ? `Kontakt: ${listing.contact_name}` : '',
    ].filter(Boolean).join('\n'),
  },
};

const COLUMNS = [
  { key: 'title', label: 'Titel', filterType: 'text' },
  { key: 'unit_label', label: 'Einheit', filterType: 'text' },
  { key: 'portal', label: 'Portal', filterType: 'select',
    render: v => PORTAL_TEMPLATES[v]?.label || v || '—' },
  { key: 'target_rent', label: 'Zielmiete (€)', type: 'number', align: 'right',
    render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
  { key: 'available_from', label: 'Verfügbar ab', type: 'date' },
  { key: 'status', label: 'Status', type: 'status', filterType: 'select',
    render: v => <StatusBadge status={v} /> },
];

export default function Listings() {
  const { t } = useTranslation();
  const [listings, setListings] = useState([]);
  const [units, setUnits] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [deleteError, setDeleteError] = useState(null);
  const [previewListing, setPreviewListing] = useState(null);
  const [previewPortal, setPreviewPortal] = useState('immoscout24');
  const [copied, setCopied] = useState(false);

  const loadData = () => {
    setLoading(true);
    Promise.all([
      api.get('/listings').catch(() => []),
      api.get('/units').catch(() => []),
    ]).then(([l, u]) => {
      setListings(l || []);
      setUnits(u || []);
    }).finally(() => setLoading(false));
  };

  useEffect(() => { loadData(); }, []);

  const unitMap = Object.fromEntries(units.map(u => [u.id, u]));
  const enriched = listings.map(l => ({
    ...l,
    unit_label: unitMap[l.unit_id]?.label || '—',
  }));

  const fields = [
    { key: 'title', label: 'Titel', required: true },
    { key: 'unit_id', label: 'Einheit', required: true, type: 'select',
      options: units.map(u => ({ value: u.id, label: u.label })) },
    { key: 'portal', label: 'Portal', type: 'select', options: [
      { value: 'immoscout24', label: 'ImmoScout24' },
      { value: 'immowelt', label: 'Immowelt' },
      { value: 'ebay', label: 'eBay Kleinanzeigen' },
      { value: 'website', label: 'Eigene Website' },
      { value: 'other', label: 'Sonstiges' },
    ]},
    { key: 'target_rent', label: 'Zielmiete (€)', type: 'number' },
    { key: 'service_charge', label: 'Nebenkosten (€)', type: 'number' },
    { key: 'available_from', label: 'Verfügbar ab', type: 'date' },
    { key: 'contact_name', label: 'Ansprechpartner' },
    { key: 'contact_email', label: 'Kontakt-E-Mail' },
    { key: 'listing_url', label: 'Link zum Inserat' },
    { key: 'status', label: 'Status', type: 'select', default: 'draft', options: [
      { value: 'draft', label: 'Entwurf' },
      { value: 'active', label: 'Aktiv' },
      { value: 'paused', label: 'Pausiert' },
      { value: 'closed', label: 'Geschlossen' },
    ]},
    { key: 'description', label: 'Beschreibung', type: 'textarea' },
  ];

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/listings', data);
    } else {
      await api.put(`/listings/${modal.id}`, data);
    }
    loadData();
  };

  const handleDelete = async (row) => {
    if (!window.confirm(`"${row.title}" ${t('modals.confirmDelete.body')}`)) return;
    setDeleteError(null);
    try {
      await api.del(`/listings/${row.id}`);
      loadData();
    } catch (err) {
      setDeleteError(err.message || 'Löschen fehlgeschlagen');
    }
  };

  const generatePreview = (listing, portal) => {
    const unit = unitMap[listing.unit_id];
    const template = PORTAL_TEMPLATES[portal];
    if (!template) return listing.description || 'Keine Vorschau verfügbar';
    return template.format(listing, unit);
  };

  const copyToClipboard = async (text) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  if (loading) return <div className="page-loading">{t('ui.table.loading')}</div>;

  return (
    <div className="page">
      {deleteError && (
        <div className="alert alert-error" style={{ marginBottom: '1rem' }}>
          {deleteError}
          <button onClick={() => setDeleteError(null)} style={{ marginLeft: '1rem', cursor: 'pointer' }}>✕</button>
        </div>
      )}

      <DataTable
        title="Inserate"
        columns={COLUMNS}
        data={enriched}
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
        onRowClick={row => setPreviewListing(row)}
      />

      {/* Platform-formatted preview panel */}
      {previewListing && (
        <div className="panel" style={{ marginTop: '1.5rem' }}>
          <div className="panel-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>Inserat-Vorschau: {previewListing.title}</span>
            <button className="btn btn-sm btn-secondary" onClick={() => setPreviewListing(null)}>Schließen</button>
          </div>
          <div className="panel-body">
            <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
              {Object.entries(PORTAL_TEMPLATES).map(([key, tmpl]) => (
                <button
                  key={key}
                  className={`btn btn-sm ${previewPortal === key ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => setPreviewPortal(key)}
                >{tmpl.label}</button>
              ))}
            </div>
            <pre style={{
              background: 'var(--bg-secondary)',
              padding: '1rem',
              borderRadius: '6px',
              whiteSpace: 'pre-wrap',
              fontSize: '0.9rem',
              lineHeight: 1.6,
              maxHeight: '400px',
              overflow: 'auto',
            }}>
              {generatePreview(previewListing, previewPortal)}
            </pre>
            <button
              className="btn btn-sm btn-primary"
              style={{ marginTop: '0.75rem' }}
              onClick={() => copyToClipboard(generatePreview(previewListing, previewPortal))}
            >
              {copied ? '✓ Kopiert!' : 'In Zwischenablage kopieren'}
            </button>
          </div>
        </div>
      )}

      {modal && (
        <FormModal
          title={modal === 'create' ? 'Inserat erstellen' : 'Inserat bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
