import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { api } from '../api';
import StatusBadge from '../components/StatusBadge';
import PhotoDropZone from '../components/PhotoDropZone';

export default function PropertyOverview() {
  const { id } = useParams();
  const [property, setProperty] = useState(null);
  const [units, setUnits] = useState([]);
  const [contracts, setContracts] = useState([]);
  const [insurances, setInsurances] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.get(`/properties/${id}`).catch(() => null),
      api.get(`/units?property_id=${id}`).catch(err => { console.warn('[PropertyOverview] units:', err.message); return []; }),
      api.get(`/contracts`).catch(err => { console.warn('[PropertyOverview] contracts:', err.message); return []; }),
      api.get(`/insurances?property_id=${id}`).catch(err => { console.warn('[PropertyOverview] insurances:', err.message); return []; }),
    ]).then(([p, u, c, ins]) => {
      setProperty(p);
      setUnits(Array.isArray(u) ? u : []);
      setContracts(Array.isArray(c) ? c : []);
      setInsurances(Array.isArray(ins) ? ins : []);
    }).finally(() => setLoading(false));
  }, [id]);

  if (loading) return <div className="page-loading">Laden...</div>;
  if (!property) return <div className="page"><p>Immobilie nicht gefunden</p></div>;

  const propertyUnits = units.filter(u => u.property_id === id);
  const unitIds = new Set(propertyUnits.map(u => u.id));
  const activeContracts = contracts.filter(c => c.status === 'active' && unitIds.has(c.unit_id));
  const occupied = propertyUnits.filter(u => u.status === 'occupied').length;
  const occupancyRate = propertyUnits.length > 0 ? Math.round((occupied / propertyUnits.length) * 100) : 0;
  const totalRent = propertyUnits.reduce((s, u) => s + (u.base_rent || 0), 0);

  return (
    <div className="page">
      <div className="overview-header">
        <div>
          <h1 className="page-title">{property.name}</h1>
          <p className="text-muted">{property.address_line}, {property.postal_code} {property.city}</p>
          <StatusBadge status={property.status} />
        </div>
        <Link to="/properties" className="btn btn-secondary">Zurück</Link>
      </div>

      <PhotoDropZone entityType="property" entityId={id} />

      <div className="overview-grid">
        <div className="panel">
          <div className="panel-header">Eckdaten</div>
          <div className="panel-body">
            <dl className="overview-dl">
              <dt>Typ</dt><dd>{property.property_type || '—'}</dd>
              <dt>Baujahr</dt><dd>{property.year_built || '—'}</dd>
              <dt>Wohnfläche</dt><dd>{property.living_area_sqm ? `${property.living_area_sqm} m²` : '—'}</dd>
              <dt>Nutzfläche</dt><dd>{property.usable_area_sqm ? `${property.usable_area_sqm} m²` : '—'}</dd>
              <dt>Grundstück</dt><dd>{property.plot_area_sqm ? `${property.plot_area_sqm} m²` : '—'}</dd>
              <dt>Kaufpreis</dt><dd>{property.purchase_price ? `${Number(property.purchase_price).toLocaleString('de-DE')} €` : '—'}</dd>
              <dt>Marktwert</dt><dd>{property.market_value ? `${Number(property.market_value).toLocaleString('de-DE')} €` : '—'}</dd>
            </dl>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">Vermietungsstatus</div>
          <div className="panel-body">
            <div className="overview-stats">
              <div className="overview-stat">
                <span className="overview-stat-value">{propertyUnits.length}</span>
                <span className="overview-stat-label">Einheiten</span>
              </div>
              <div className="overview-stat">
                <span className="overview-stat-value">{occupied}/{propertyUnits.length}</span>
                <span className="overview-stat-label">Vermietet</span>
              </div>
              <div className="overview-stat">
                <span className="overview-stat-value">{occupancyRate}%</span>
                <span className="overview-stat-label">Auslastung</span>
              </div>
              <div className="overview-stat">
                <span className="overview-stat-value">{totalRent.toLocaleString('de-DE')} €</span>
                <span className="overview-stat-label">Gesamtmiete/Monat</span>
              </div>
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">Aktive Verträge ({activeContracts.length})</div>
          <div className="panel-body">
            {activeContracts.length === 0 ? (
              <p className="empty-text">Keine aktiven Verträge</p>
            ) : (
              <ul className="overview-list">
                {activeContracts.slice(0, 5).map(c => (
                  <li key={c.id}>
                    <span>{c.contract_number}</span>
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
              <p className="empty-text">Keine Versicherungen</p>
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
