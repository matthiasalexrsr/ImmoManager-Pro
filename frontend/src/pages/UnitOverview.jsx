import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useTranslation } from '../i18n';
import { api } from '../api';
import StatusBadge from '../components/StatusBadge';
import PhotoDropZone from '../components/PhotoDropZone';

export default function UnitOverview() {
  const { t } = useTranslation();
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

  if (loading) return <div className="page-loading">{t('pages.loading') || 'Laden...'}</div>;
  if (!unit) return <div className="page"><p>{t('pages.unitOverview.notFound') || 'Einheit nicht gefunden'}</p></div>;

  const activeContract = contracts.find(c => c.status === 'active');

  return (
    <div className="page">
      <div className="overview-header">
        <div>
          <h1 className="page-title">{unit.label || `${t('pages.unitOverview.unitLabel') || 'Einheit'} ${unit.unit_number}`}</h1>
          {property && <p className="text-muted">{property.name} — {property.address_line}</p>}
          <StatusBadge status={unit.status} />
        </div>
        <Link to="/units" className="btn btn-secondary">{t('pages.unitOverview.back') || 'Zurück'}</Link>
      </div>

      <PhotoDropZone entityType="unit" entityId={id} />

      <div className="overview-grid">
        <div className="panel">
          <div className="panel-header">{t('pages.unitOverview.keyData') || 'Eckdaten'}</div>
          <div className="panel-body">
            <dl className="overview-dl">
              <dt>{t('pages.unitOverview.unitNumber') || 'Einheitsnr.'}</dt><dd>{unit.unit_number || '—'}</dd>
              <dt>{t('pages.unitOverview.type') || 'Typ'}</dt><dd>{unit.unit_type || '—'}</dd>
              <dt>{t('pages.unitOverview.floor') || 'Etage'}</dt><dd>{unit.floor ?? '—'}</dd>
              <dt>{t('pages.unitOverview.area') || 'Fläche'}</dt><dd>{unit.area_sqm ? `${unit.area_sqm} m²` : '—'}</dd>
              <dt>{t('pages.unitOverview.rooms') || 'Zimmer'}</dt><dd>{unit.rooms ?? '—'}</dd>
              <dt>{t('pages.unitOverview.personCount') || 'Personenzahl'}</dt><dd>{unit.person_count ?? '—'}</dd>
              <dt>{t('pages.unitOverview.features') || 'Ausstattung'}</dt><dd>{unit.features || '—'}</dd>
              <dt>{t('pages.unitOverview.baseRent') || 'Kaltmiete'}</dt><dd>{unit.base_rent ? `${Number(unit.base_rent).toFixed(2)} €` : '—'}</dd>
              <dt>{t('pages.unitOverview.serviceCharge') || 'Nebenkosten'}</dt><dd>{unit.service_charge ? `${Number(unit.service_charge).toFixed(2)} €` : '—'}</dd>
              <dt>{t('pages.unitOverview.heatingAdvance') || 'Heizkosten'}</dt><dd>{unit.heating_advance ? `${Number(unit.heating_advance).toFixed(2)} €` : '—'}</dd>
            </dl>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">{t('pages.unitOverview.rentalStatus') || 'Mietstatus'}</div>
          <div className="panel-body">
            {activeContract ? (
              <dl className="overview-dl">
                <dt>{t('pages.unitOverview.contract') || 'Vertrag'}</dt><dd>{activeContract.contract_number}</dd>
                <dt>{t('pages.unitOverview.tenant') || 'Mieter'}</dt><dd>{tenant?.full_name || '—'}</dd>
                <dt>{t('pages.unitOverview.start') || 'Beginn'}</dt><dd>{activeContract.start_date || '—'}</dd>
                <dt>{t('pages.unitOverview.end') || 'Ende'}</dt><dd>{activeContract.end_date || t('pages.unitOverview.indefinite') || 'Unbefristet'}</dd>
                <dt>{t('pages.unitOverview.deposit') || 'Kaution'}</dt><dd>{activeContract.deposit_amount ? `${Number(activeContract.deposit_amount).toFixed(2)} €` : '—'}</dd>
              </dl>
            ) : (
              <p className="empty-text">{t('pages.unitOverview.notRented') || 'Nicht vermietet'}</p>
            )}
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">{t('pages.unitOverview.contractHistory') || 'Vertragshistorie'} ({contracts.length})</div>
          <div className="panel-body">
            {contracts.length === 0 ? (
              <p className="empty-text">{t('pages.unitOverview.noContracts') || 'Keine Verträge'}</p>
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
          <div className="panel-header">{t('pages.unitOverview.insurances') || 'Versicherungen'} ({insurances.length})</div>
          <div className="panel-body">
            {insurances.length === 0 ? (
              <p className="empty-text">{t('pages.unitOverview.noUnitInsurances') || 'Keine einheitsspezifischen Versicherungen'}</p>
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
