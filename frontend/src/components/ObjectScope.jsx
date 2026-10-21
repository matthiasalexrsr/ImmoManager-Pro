import { Link } from 'react-router-dom';
import { scopeDefaults } from '../utils/objectScope';

/** Keep the origin of a filtered collection visible, with a route back to its file. */
export default function ObjectScope({ params, setParams, properties = [], units = [] }) {
  const { property_id: propertyId, unit_id: unitId } = scopeDefaults(params, units);
  if (!propertyId && !unitId) return null;
  return <nav className="filter-chips" aria-label="Objektbezug">
    <span>Auswahl:</span>
    {propertyId && <Link to={`/properties/${encodeURIComponent(propertyId)}`}>
      {properties.find(property => property.id === propertyId)?.name || 'Immobilie öffnen'}</Link>}
    {unitId && <Link to={`/units/${encodeURIComponent(unitId)}`}>
      {units.find(unit => unit.id === unitId)?.label || 'Einheit öffnen'}</Link>}
    <button type="button" className="btn btn-secondary btn-sm" onClick={() => setParams(current => {
      const next = new URLSearchParams(current);
      ['property_id', 'unit_id', 'focus_id', 'suche'].forEach(key => next.delete(key));
      return next;
    })}>Objektfilter aufheben</button>
  </nav>;
}
