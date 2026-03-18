import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { api } from '../api';
import StatusBadge from '../components/StatusBadge';
import PhotoDropZone from '../components/PhotoDropZone';

export default function UnitOverview() {
  const { id } = useParams();
  const [unit, setUnit] = useState(null);
  const [property, setProperty] = useState(null);
  const [contracts, setContracts] = useState([]);
  const [tenant, setTenant] = useState(null);
  const [insurances, setInsurances] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get(`/units/${id}`).then(u => {
      setUnit(u);
      return Promise.all([
        u.property_id ? api.get(`/properties/${u.property_id}`).catch(() => null) : null,
        api.get(`/contracts`).catch(err => { console.warn('[UnitOverview] contracts:', err.message); return []; }),
        api.get(`/insurances?unit_id=${id}`).catch(err => { console.warn('[UnitOverview] insurances:', err.message); return []; }),
      ]);
    }).then(([p, c, ins]) => {
      setProperty(p);
      const unitContracts = (Array.isArray(c) ? c : []).filter(ct => ct.unit_id === id);
      setContracts(unitContracts);
      const active = unitContracts.find(ct => ct.status === 'active');
      if (active?.tenant_id) {
        api.get(`/tenants/${active.tenant_id}`).then(setTenant).catch(() => null);
      }
      setInsurances(Array.isArray(ins) ? ins : []);
    }).catch(() => null).finally(() => setLoading(false));
  }, [id]);

  if (loading) return <div className="page-loading">Laden...</div>;
  if (!unit) return <div className="page"><p>Einheit nicht gefunden</p></div>;

  const activeContract = contracts.find(c => c.status === 'active');

  return (
    <div className="page">
      <div className="overview-header">
        <div>
          <h1 className="page-title">{unit.label || `Einheit ${unit.unit_number}`}</h1>
          {property && <p className="text-muted">{property.name} — {property.address_line}</p>}
          <StatusBadge status={unit.status} />
        </div>
        <Link to="/units" className="btn btn-secondary">Zurück</Link>
      </div>

      <PhotoDropZone entityType="unit" entityId={id} />

      <div className="overview-grid">
        <div className="panel">
          <div className="panel-header">Eckdaten</div>
          <div className="panel-body">
            <dl className="overview-dl">
              <dt>Einheitsnr.</dt><dd>{unit.unit_number || '—'}</dd>
              <dt>Typ</dt><dd>{unit.unit_type || '—'}</dd>
              <dt>Etage</dt><dd>{unit.floor ?? '—'}</dd>
              <dt>Fläche</dt><dd>{unit.area_sqm ? `${unit.area_sqm} m²` : '—'}</dd>
              <dt>Zimmer</dt><dd>{unit.rooms ?? '—'}</dd>
              <dt>Personenzahl</dt><dd>{unit.person_count ?? '—'}</dd>
              <dt>Ausstattung</dt><dd>{unit.features || '—'}</dd>
              <dt>Kaltmiete</dt><dd>{unit.base_rent ? `${Number(unit.base_rent).toFixed(2)} €` : '—'}</dd>
              <dt>Nebenkosten</dt><dd>{unit.service_charge ? `${Number(unit.service_charge).toFixed(2)} €` : '—'}</dd>
              <dt>Heizkosten</dt><dd>{unit.heating_advance ? `${Number(unit.heating_advance).toFixed(2)} €` : '—'}</dd>
            </dl>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">Mietstatus</div>
          <div className="panel-body">
            {activeContract ? (
              <dl className="overview-dl">
                <dt>Vertrag</dt><dd>{activeContract.contract_number}</dd>
                <dt>Mieter</dt><dd>{tenant?.full_name || '—'}</dd>
                <dt>Beginn</dt><dd>{activeContract.start_date || '—'}</dd>
                <dt>Ende</dt><dd>{activeContract.end_date || 'Unbefristet'}</dd>
                <dt>Kaution</dt><dd>{activeContract.deposit_amount ? `${Number(activeContract.deposit_amount).toFixed(2)} €` : '—'}</dd>
              </dl>
            ) : (
              <p className="empty-text">Nicht vermietet</p>
            )}
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">Vertragshistorie ({contracts.length})</div>
          <div className="panel-body">
            {contracts.length === 0 ? (
              <p className="empty-text">Keine Verträge</p>
            ) : (
              <ul className="overview-list">
                {contracts.map(c => (
                  <li key={c.id}>
                    <span>{c.contract_number} ({c.start_date} — {c.end_date || '∞'})</span>
                    <StatusBadge status={c.status} />
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">Versicherungen ({insurances.length})</div>
          <div className="panel-body">
            {insurances.length === 0 ? (
              <p className="empty-text">Keine einheitsspezifischen Versicherungen</p>
            ) : (
              <ul className="overview-list">
                {insurances.map(ins => (
                  <li key={ins.id}>
                    <span>{ins.provider} — {ins.insurance_type}</span>
                    <StatusBadge status={ins.status} />
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
