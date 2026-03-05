import { useState, useEffect } from 'react';
import { api } from '../api';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';

const COLUMNS = [
  { key: 'property_name', label: 'Immobilie', filterType: 'text' },
  { key: 'period_label', label: 'Abrechnungszeitraum', filterType: 'text' },
  { key: 'total_costs', label: 'Gesamtkosten (€)', type: 'number', align: 'right',
    render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
  { key: 'units_count', label: 'Einheiten', type: 'number' },
  { key: 'status', label: 'Status', type: 'status', filterType: 'select' },
];

const COST_COLUMNS = [
  { key: 'description', label: 'Kostenart', filterType: 'text' },
  { key: 'amount', label: 'Betrag (€)', type: 'number', align: 'right',
    render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
  { key: 'allocation_key_name', label: 'Verteilerschlüssel' },
];

const STMT_COLUMNS = [
  { key: 'unit_label', label: 'Einheit' },
  { key: 'total_cost', label: 'Anteil (€)', type: 'number', align: 'right',
    render: v => `${Number(v || 0).toFixed(2)} €` },
  { key: 'advance_paid', label: 'Vorauszahlung (€)', type: 'number', align: 'right',
    render: v => `${Number(v || 0).toFixed(2)} €` },
  { key: 'balance', label: 'Saldo (€)', type: 'number', align: 'right',
    render: (v) => {
      const cls = v > 0 ? 'text-red' : v < 0 ? 'text-green' : '';
      return <span className={cls}>{Number(v || 0).toFixed(2)} €</span>;
    }},
  { key: 'status', label: 'Status', type: 'status' },
];

export default function Statements() {
  const [periods, setPeriods] = useState([]);
  const [costItems, setCostItems] = useState([]);
  const [statements, setStatements] = useState([]);
  const [properties, setProperties] = useState([]);
  const [units, setUnits] = useState([]);
  const [allocationKeys, setAllocationKeys] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [selectedPeriod, setSelectedPeriod] = useState(null);
  const [costModal, setCostModal] = useState(null);
  const [view, setView] = useState('list');
  const [preflight, setPreflight] = useState(null);
  const [preflightLoading, setPreflightLoading] = useState(false);
  const [finalizing, setFinalizing] = useState(false);

  const loadData = () => {
    Promise.all([
      api.get('/billing/periods').catch(() => []),
      api.get('/billing/cost-items').catch(() => []),
      api.get('/billing/utility-statements').catch(() => []),
      api.get('/properties').catch(() => []),
      api.get('/units').catch(() => []),
      api.get('/billing/allocation-keys').catch(() => []),
    ]).then(([bp, ci, us, props, u, ak]) => {
      setPeriods(bp || []);
      setCostItems(ci || []);
      setStatements(us || []);
      setProperties(props || []);
      setUnits(u || []);
      setAllocationKeys(ak || []);
    }).finally(() => setLoading(false));
  };

  useEffect(() => { loadData(); }, []);

  const propMap = Object.fromEntries(properties.map(p => [p.id, p]));
  const unitMap = Object.fromEntries(units.map(u => [u.id, u]));
  const akMap = Object.fromEntries(allocationKeys.map(k => [k.id, k]));

  const enriched = periods.map(bp => {
    const costs = costItems.filter(ci => ci.billing_period_id === bp.id);
    const totalCosts = costs.reduce((s, c) => s + (c.amount || 0), 0);
    const stmts = statements.filter(s => s.billing_period_id === bp.id);
    return {
      ...bp,
      property_name: propMap[bp.property_id]?.name || '—',
      period_label: `${bp.start_date || '?'} – ${bp.end_date || '?'}`,
      total_costs: totalCosts,
      units_count: stmts.length,
    };
  });

  const fields = [
    { key: 'property_id', label: 'Immobilie', type: 'select', required: true,
      options: properties.map(p => ({ value: p.id, label: p.name })) },
    { key: 'label', label: 'Bezeichnung', required: true, placeholder: 'z.B. NK-Abrechnung 2025' },
    { key: 'start_date', label: 'Beginn', type: 'date', required: true },
    { key: 'end_date', label: 'Ende', type: 'date', required: true },
    { key: 'status', label: 'Status', type: 'select', default: 'draft', options: [
      { value: 'draft', label: 'Entwurf' },
      { value: 'finalized', label: 'Abgeschlossen' },
    ]},
  ];

  const costFields = [
    { key: 'billing_period_id', label: 'Abrechnungsperiode', type: 'select', required: true,
      options: periods.map(p => ({ value: p.id, label: p.label || `${p.start_date} – ${p.end_date}` })) },
    { key: 'description', label: 'Kostenart', required: true, placeholder: 'z.B. Wasser, Heizung, Müll' },
    { key: 'amount', label: 'Betrag (€)', type: 'number', required: true },
    { key: 'allocation_key_id', label: 'Verteilerschlüssel', type: 'select', required: true,
      options: allocationKeys.map(k => ({ value: k.id, label: `${k.name} (${k.key_type})` })) },
  ];

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/billing/periods', data);
    } else if (modal === 'copy') {
      const newPeriod = await api.post('/billing/periods', data);
      if (newPeriod && selectedPeriod) {
        const prevCosts = costItems.filter(ci => ci.billing_period_id === selectedPeriod.id);
        for (const cost of prevCosts) {
          await api.post('/billing/cost-items', {
            billing_period_id: newPeriod.id,
            description: cost.description,
            amount: 0,
            allocation_key_id: cost.allocation_key_id,
          }).catch(() => {});
        }
      }
    } else {
      await api.put(`/billing/periods/${modal.id}`, data);
    }
    loadData();
  };

  const handleSaveCost = async (data) => {
    if (costModal === 'create') {
      await api.post('/billing/cost-items', data);
    } else {
      await api.put(`/billing/cost-items/${costModal.id}`, data);
    }
    loadData();
  };



  const handleFinalizePeriod = async () => {
    if (!selectedPeriod || selectedPeriod.status === 'finalized') return;
    setFinalizing(true);
    try {
      const updated = await api.post(`/billing/periods/${selectedPeriod.id}/finalize`, {});
      setSelectedPeriod(updated);
      await loadData();
      const pf = await api.get(`/billing/periods/${selectedPeriod.id}/preflight`).catch(() => null);
      setPreflight(pf);
    } catch (err) {
      window.alert(err.message || 'Finalisierung fehlgeschlagen');
    } finally {
      setFinalizing(false);
    }
  };

  const handleSelectPeriod = (period) => {
    setSelectedPeriod(period);
    setView('detail');
    setPreflight(null);
    setPreflightLoading(true);
    api.get(`/billing/periods/${period.id}/preflight`)
      .then(setPreflight)
      .catch(() => setPreflight(null))
      .finally(() => setPreflightLoading(false));
  };

  if (loading) return <div className="page-loading">Laden...</div>;

  if (view === 'detail' && selectedPeriod) {
    const periodCosts = costItems.filter(ci => ci.billing_period_id === selectedPeriod.id)
      .map(ci => ({ ...ci, allocation_key_name: akMap[ci.allocation_key_id]?.name || '—' }));
    const periodStmts = statements.filter(s => s.billing_period_id === selectedPeriod.id)
      .map(s => ({ ...s, unit_label: unitMap[s.unit_id]?.label || '—' }));
    const totalCosts = periodCosts.reduce((s, c) => s + (c.amount || 0), 0);

    return (
      <div className="page">
        <div className="detail-header">
          <button className="btn btn-sm btn-secondary" onClick={() => setView('list')}>
            ← Zurück
          </button>
          <div className="detail-title">
            <h1>{selectedPeriod.label || 'Abrechnung'}</h1>
            <span className="text-muted">
              {propMap[selectedPeriod.property_id]?.name || '—'} · {selectedPeriod.start_date} – {selectedPeriod.end_date}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <StatusBadge status={selectedPeriod.status} />
            <button
              className="btn btn-sm btn-primary"
              onClick={handleFinalizePeriod}
              disabled={selectedPeriod.status === 'finalized' || finalizing || preflightLoading || preflight?.has_blockers}
            >
              {finalizing ? 'Finalisiere…' : (selectedPeriod.status === 'finalized' ? 'Finalisiert' : 'Finalisieren')}
            </button>
          </div>
        </div>

        <div className="stats-grid" style={{ marginBottom: '1rem' }}>
          <div className="stat-card">
            <div className="stat-label">Gesamtkosten</div>
            <div className="stat-value">{totalCosts.toFixed(2)} €</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Kostenpositionen</div>
            <div className="stat-value">{periodCosts.length}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Einzelabrechnungen</div>
            <div className="stat-value">{periodStmts.length}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Status</div>
            <div className="stat-value"><StatusBadge status={selectedPeriod.status} /></div>
          </div>
        </div>

        <div className="card" style={{ marginBottom: '1rem' }}>
          <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <strong>Preflight (Abrechnungsbereitschaft)</strong>
            <button
              className="btn btn-sm btn-secondary"
              onClick={() => {
                setPreflightLoading(true);
                api.get(`/billing/periods/${selectedPeriod.id}/preflight`)
                  .then(setPreflight)
                  .catch(() => setPreflight(null))
                  .finally(() => setPreflightLoading(false));
              }}
            >
              Neu prüfen
            </button>
          </div>
          <div className="card-body">
            {preflightLoading && <span className="text-muted">Prüfung läuft…</span>}
            {!preflightLoading && !preflight && <span className="text-muted">Keine Preflight-Daten verfügbar.</span>}
            {!preflightLoading && preflight && (
              <div style={{ display: 'grid', gap: '0.75rem' }}>
                <div>
                  <span className={`badge ${preflight.has_blockers ? 'badge-danger' : 'badge-success'}`}>
                    {preflight.has_blockers ? 'Blockiert' : 'Bereit zur Generierung'}
                  </span>
                </div>
                {preflight.blockers?.length > 0 && (
                  <div>
                    <strong>Blocker</strong>
                    <ul>
                      {preflight.blockers.map((i) => (
                        <li key={`${i.code}-${i.context || ''}`}>{i.message}{i.context ? ` (${i.context})` : ''}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {preflight.warnings?.length > 0 && (
                  <div>
                    <strong>Warnungen</strong>
                    <ul>
                      {preflight.warnings.map((i) => (
                        <li key={`${i.code}-${i.context || ''}`}>{i.message}{i.context ? ` (${i.context})` : ''}</li>
                      ))}
                    </ul>
                  </div>
                )}
                <div>
                  <strong>Kennzahlen</strong>
                  <div className="text-muted" style={{ fontSize: '0.9rem' }}>
                    Verträge: {preflight.metrics?.contracts_in_period ?? 0} · Kostenpositionen: {preflight.metrics?.cost_items ?? 0} ·
                    Fehlende Schlüssel: {preflight.metrics?.allocation_keys_missing ?? 0} · Fehlende Flächen: {preflight.metrics?.area_missing_units ?? 0}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        <div style={{ marginBottom: '1.5rem' }}>
          <DataTable
            title="Kostenpositionen"
            columns={COST_COLUMNS}
            data={periodCosts}
            onAdd={selectedPeriod.status === 'finalized' ? undefined : () => setCostModal('create')}
            onEdit={selectedPeriod.status === 'finalized' ? undefined : (row => setCostModal(row))}
          />
        </div>

        {periodStmts.length > 0 && (
          <DataTable
            title="Einzelabrechnungen pro Einheit"
            columns={STMT_COLUMNS}
            data={periodStmts}
          />
        )}

        {costModal && selectedPeriod.status !== 'finalized' && (
          <FormModal
            title={costModal === 'create' ? 'Kostenposition hinzufügen' : 'Kostenposition bearbeiten'}
            fields={costFields}
            initial={costModal === 'create' ? { billing_period_id: selectedPeriod.id } : costModal}
            onSave={handleSaveCost}
            onClose={() => setCostModal(null)}
          />
        )}
      </div>
    );
  }

  return (
    <div className="page">
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
        {selectedPeriod && (
          <button className="btn btn-sm btn-secondary" onClick={() => setModal('copy')}>
            Vorjahr kopieren
          </button>
        )}
      </div>
      <DataTable
        title="Nebenkostenabrechnungen"
        columns={COLUMNS}
        data={enriched}
        onAdd={() => setModal('create')}
        onEdit={handleSelectPeriod}
      />
      {(modal === 'create' || modal === 'copy') && (
        <FormModal
          title={modal === 'copy' ? 'Abrechnung kopieren (neuer Zeitraum)' : 'Abrechnung erstellen'}
          fields={fields}
          initial={modal === 'copy' && selectedPeriod ? {
            property_id: selectedPeriod.property_id,
            label: `${selectedPeriod.label} (Kopie)`,
          } : null}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
      {modal && modal !== 'create' && modal !== 'copy' && modal.id && (
        <FormModal
          title="Abrechnung bearbeiten"
          fields={fields}
          initial={modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
