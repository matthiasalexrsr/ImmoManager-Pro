import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useTranslation } from '../i18n';
import { api } from '../api';
import StatusBadge from '../components/StatusBadge';
import PhotoDropZone from '../components/PhotoDropZone';
import { formatDate, formatMoney } from '../utils/format';
import { codeLabel } from '../utils/codeLabels';
import { PartyLink } from '../features/partyWorkspace/PartyWorkspace';
import './propertyDossier.css';

export default function UnitOverview() {
  const { t } = useTranslation();
  const { id } = useParams();
  const [unit, setUnit] = useState(null);
  const [property, setProperty] = useState(null);
  const [contracts, setContracts] = useState([]);
  const [tenant, setTenant] = useState(null);
  const [insurances, setInsurances] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const options = { signal: controller.signal };
    setLoading(true);
    setError(null);
    setTenant(null);
    (async () => {
      const u = await api.get(`/units/${encodeURIComponent(id)}`, options);
      const [p, c, ins] = await Promise.all([
        u.property_id ? api.get(`/properties/${encodeURIComponent(u.property_id)}`, options) : null,
        api.list(`/contracts?unit_id=${encodeURIComponent(id)}`, options),
        api.list(`/insurances?unit_id=${encodeURIComponent(id)}`, options),
      ]);
      const unitContracts = c.filter(ct => ct.unit_id === id);
      const active = unitContracts.find(ct => ct.status === 'active');
      const person = active?.tenant_id ? await api.get(`/tenants/${encodeURIComponent(active.tenant_id)}`, options) : null;
      if (cancelled) return;
      setUnit(u); setProperty(p); setContracts(unitContracts); setTenant(person); setInsurances(ins);
    })().catch(err => { if (!cancelled) setError(err.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; controller.abort(); };
  }, [id, revision]);

  if (loading) return <div className="page-loading">{t('pages.loading') || 'Laden...'}</div>;
  if (error) return <div className="page"><div role="alert" className="alert alert-error">{error}</div><button className="btn btn-secondary" onClick={() => setRevision(value => value + 1)}>Erneut laden</button></div>;
  if (!unit) return <div className="page"><p>{t('pages.unitOverview.notFound') || 'Einheit nicht gefunden'}</p></div>;

  const activeContract = contracts.find(c => c.status === 'active');

  return (
    <div className="page unit-dossier">
      <div className="overview-header">
        <div>
          <h1 className="page-title">{unit.label || `${t('pages.unitOverview.unitLabel') || 'Einheit'} ${unit.unit_number}`}</h1>
          {property && <p className="text-muted"><Link to={`/properties/${encodeURIComponent(unit.property_id)}`}>{property.name}</Link> — {property.address_line}</p>}
          <StatusBadge status={unit.status} />
        </div>
        <div className="dossier-navigation">
          {property && <Link to={`/properties/${encodeURIComponent(unit.property_id)}`} className="btn btn-secondary">← Zur Immobilie</Link>}
          <Link to="/units" className="btn btn-secondary">Alle Einheiten</Link>
        </div>
      </div>

      <PhotoDropZone entityType="unit" entityId={id} />

      <div className="overview-grid">
        <div className="panel">
          <div className="panel-header">{t('pages.unitOverview.keyData') || 'Eckdaten'}</div>
          <div className="panel-body">
            <dl className="overview-dl">
              <dt>{t('pages.unitOverview.unitNumber') || 'Einheitsnr.'}</dt><dd>{unit.unit_number || '—'}</dd>
              <dt>{t('pages.unitOverview.type') || 'Typ'}</dt><dd>{codeLabel(unit.unit_type) || '—'}</dd>
              <dt>{t('pages.unitOverview.floor') || 'Etage'}</dt><dd>{unit.floor ?? '—'}</dd>
              <dt>{t('pages.unitOverview.area') || 'Fläche'}</dt><dd>{unit.area_sqm ? `${unit.area_sqm} m²` : '—'}</dd>
              <dt>{t('pages.unitOverview.rooms') || 'Zimmer'}</dt><dd>{unit.rooms ?? '—'}</dd>
              <dt>{t('pages.unitOverview.personCount') || 'Personenzahl'}</dt><dd>{unit.person_count ?? '—'}</dd>
              <dt>{t('pages.unitOverview.features') || 'Ausstattung'}</dt><dd>{unit.features || '—'}</dd>
              <dt>Plan-Kaltmiete</dt><dd>{unit.cold_rent != null ? `${formatMoney(unit.cold_rent)}` : '—'}</dd>
              <dt>Plan-Nebenkosten</dt><dd>{unit.service_charge_advance != null ? `${formatMoney(unit.service_charge_advance)}` : '—'}</dd>
              <dt>Plan-Heizkosten</dt><dd>{unit.heating_advance ? `${formatMoney(unit.heating_advance)}` : '—'}</dd>
            </dl>
            <p className="text-muted dossier-rent-note">Planmieten aus den Stammdaten der Einheit. Die vereinbarte Miete steht im Mietvertrag.</p>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">{t('pages.unitOverview.rentalStatus') || 'Mietstatus'}</div>
          <div className="panel-body">
            {activeContract ? (
              <dl className="overview-dl">
                <dt>{t('pages.unitOverview.contract') || 'Vertrag'}</dt><dd>{activeContract.contract_number}</dd>
                <dt>{t('pages.unitOverview.tenant') || 'Mieter'}</dt><dd><PartyLink tenantId={tenant?.id}>{tenant?.full_name || '—'}</PartyLink></dd>
                <dt>{t('pages.unitOverview.start') || 'Beginn'}</dt><dd>{formatDate(activeContract.start_date)}</dd>
                <dt>{t('pages.unitOverview.end') || 'Ende'}</dt><dd>{activeContract.end_date ? formatDate(activeContract.end_date) : t('pages.unitOverview.indefinite') || 'Unbefristet'}</dd>
                <dt>{t('pages.unitOverview.deposit') || 'Kaution'}</dt><dd>{activeContract.deposit_amount ? `${formatMoney(activeContract.deposit_amount)}` : '—'}</dd>
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
                    <span>{c.contract_number} ({formatDate(c.start_date)} – {c.end_date ? formatDate(c.end_date) : 'unbefristet'})</span>
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
