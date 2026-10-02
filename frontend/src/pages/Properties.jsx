import { revisionOptions } from '../editRevision';
import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Building2, MapPin, ArrowUpRight, Plus, Search, LayoutGrid, List, RefreshCw, Pencil, Trash2, Wrench, Home } from 'lucide-react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import useWriteAccess from '../hooks/useWriteAccess';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import { useConfirm } from '../components/ConfirmDialog';
import './Properties.css';

function PropertyStatus({ status, t }) {
  if (!status) return null;
  const key = `properties.statusLabels.${status}`;
  const label = t(key);
  return <span className="property-status" data-status={status}>{label === key ? status : label}</span>;
}

const occupied = unit => ['occupied', 'rented'].includes(unit.status);
const number = value => value == null || value === '' || !Number.isFinite(Number(value)) ? null : Number(value);

export default function Properties() {
  const { t, locale } = useTranslation();
  const navigate = useNavigate();
  const confirm = useConfirm();
  const store = useDataStore();
  const portfoliosData = useEntities('portfolios', '/portfolios');
  const unitsData = useEntities('units', '/units');
  const maintenanceData = useEntities('maintenance', '/maintenance');
  const { items: portfolios } = portfoliosData;
  const [properties, setProperties] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [modal, setModal] = useState(null);
  const { canWrite, isAllowed, requireWrite } = useWriteAccess('/properties', () => setModal(null));
  const [filter, setFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [portfolioFilter, setPortfolioFilter] = useState('');
  const [sort, setSort] = useState('name');
  const [view, setView] = useState('cards');
  const requestRef = useRef(null);
  const unitsReady = !unitsData.loading && !unitsData.error;
  const maintenanceReady = !maintenanceData.loading && !maintenanceData.error;
  const money = value => value == null ? '—' : new Intl.NumberFormat(locale, { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(value);
  const count = value => new Intl.NumberFormat(locale).format(value);

  const refreshData = useCallback(async () => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const data = await api.getAll('/properties', { signal: controller.signal });
      if (!Array.isArray(data)) throw new Error('Invalid property response');
      if (!controller.signal.aborted) setProperties(data);
    } catch (err) {
      if (!controller.signal.aborted) setError(err.message);
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshData();
    return () => requestRef.current?.abort();
  }, [refreshData]);

  const enriched = useMemo(() => {
    const portfolioMap = Object.fromEntries(portfolios.map(p => [p.id, p.name]));
    return properties.map(prop => {
      const propertyUnits = unitsData.items.filter(unit => unit.property_id === prop.id);
      const rented = propertyUnits.filter(occupied).length;
      const vacant = propertyUnits.filter(unit => unit.status === 'vacant').length;
      const rentKnown = propertyUnits.every(unit => number(unit.cold_rent) != null);
      const open = maintenanceData.items.filter(item => item.property_id === prop.id && ['open', 'in_progress'].includes(item.status)).length;
      return { ...prop,
        address: [prop.address_line, [prop.postal_code, prop.city].filter(Boolean).join(' ')].filter(Boolean).join(', '),
        portfolio_name: portfolioMap[prop.portfolio_id] || '—',
        unit_count: unitsReady ? propertyUnits.length : null,
        occupied_count: rented,
        vacant_count: vacant,
        occupancy_rate: unitsReady && propertyUnits.length ? Math.round(rented / propertyUnits.length * 100) : null,
        total_rent: unitsReady && rentKnown ? propertyUnits.reduce((sum, unit) => sum + number(unit.cold_rent), 0) : null,
        open_maintenance: maintenanceReady ? open : null,
      };
    });
  }, [properties, portfolios, unitsData.items, maintenanceData.items, unitsReady, maintenanceReady]);

  const filtered = useMemo(() => {
    const query = search.trim().toLocaleLowerCase(locale);
    const result = enriched.filter(prop => {
      if (portfolioFilter && prop.portfolio_id !== portfolioFilter) return false;
      if (filter === 'active' || filter === 'inactive') { if (prop.status !== filter) return false; }
      if (filter === 'vacancy' && (!unitsReady || !prop.vacant_count)) return false;
      if (filter === 'open_maintenance' && !prop.open_maintenance) return false;
      return !query || [prop.name, prop.address, prop.portfolio_name, prop.property_type].some(value => String(value || '').toLocaleLowerCase(locale).includes(query));
    });
    return result.sort((a, b) => sort === 'rent'
      ? (b.total_rent ?? -1) - (a.total_rent ?? -1) || String(a.name).localeCompare(String(b.name), locale)
      : String(a[sort] || '').localeCompare(String(b[sort] || ''), locale));
  }, [enriched, filter, search, portfolioFilter, sort, locale, unitsReady]);

  const totalUnits = unitsReady ? enriched.reduce((sum, p) => sum + p.unit_count, 0) : null;
  const totalOccupied = enriched.reduce((sum, p) => sum + p.occupied_count, 0);
  const occupancyRate = unitsReady && totalUnits > 0 ? Math.round(totalOccupied / totalUnits * 100) : null;
  const hasFilters = Boolean(search || portfolioFilter || filter !== 'all');
  const resetFilters = () => { setSearch(''); setPortfolioFilter(''); setFilter('all'); };
  const reloadAll = () => { void refreshData(); portfoliosData.reload(); unitsData.reload(); maintenanceData.reload(); };
  const typeLabel = type => {
    const key = `properties.typeLabels.${type}`;
    return t(key) === key ? type || '—' : t(key);
  };
  const columns = [
    { key: 'name', label: t('properties.object'), render: (value, row) => <Link className="property-table-identity" to={`/properties/${row.id}`} onClick={event => event.stopPropagation()}><strong>{value}</strong><span>{row.address || t('properties.noAddress')}</span></Link> },
    { key: 'portfolio_name', label: t('properties.portfolio') },
    { key: 'unit_count', label: t('properties.units'), type: 'number', align: 'right', render: value => value ?? '—' },
    { key: 'occupancy_rate', label: t('properties.occupancy'), type: 'number', align: 'right', render: value => value == null ? '—' : `${value}%` },
    { key: 'total_rent', label: t('properties.monthlyRent'), type: 'number', align: 'right', render: money },
    { key: 'open_maintenance', label: t('properties.openMaintenance'), type: 'number', align: 'right', render: value => value ?? '—' },
    { key: 'status', label: t('ui.form.status'), render: value => <PropertyStatus status={value} t={t} /> },
  ];

  const sStamm = t('properties.form.general.title') || 'Stammdaten';
  const sAddr = t('properties.form.location.title') || 'Adresse';
  const sArea = t('properties.form.metrics.title') || 'Flächen';
  const sFin = t('properties.form.ownership.title') || 'Kauf & Bewertung';

  const fields = useMemo(() => [
    { section: sStamm, key: 'portfolio_id', label: 'Portfolio', required: true, type: 'select',
      options: portfolios.map(p => ({ value: p.id, label: p.name })) },
    { section: sStamm, key: 'name', label: t('properties.form.general.name') || 'Name', required: true },
    { section: sStamm, key: 'property_type', label: t('properties.form.general.type') || 'Typ', required: true, type: 'select', options: [
      { value: 'residential', label: t('properties.typeLabels.residential') || 'Wohngebäude' },
      { value: 'commercial', label: t('properties.typeLabels.commercial') || 'Gewerbe' },
      { value: 'mixed', label: t('properties.typeLabels.mixed') || 'Gemischt' },
    ]},
    { section: sStamm, key: 'status', label: t('ui.form.status') || 'Status', type: 'select', default: 'active', options: [
      { value: 'active', label: t('properties.statusLabels.active') || 'Aktiv' },
      { value: 'inactive', label: t('properties.statusLabels.inactive') || 'Inaktiv' },
    ]},
    { section: sAddr, key: 'address_line', label: t('properties.form.location.street') || 'Straße' },
    { section: sAddr, key: 'postal_code', label: t('properties.form.location.postalCode') || 'PLZ' },
    { section: sAddr, key: 'city', label: t('properties.form.location.city') || 'Stadt' },
    { section: sAddr, key: 'country', label: t('properties.form.location.country') || 'Land', default: 'DE' },
    { section: sArea, key: 'year_built', label: t('properties.form.metrics.yearBuilt') || 'Baujahr', type: 'number' },
    { section: sArea, key: 'living_area_sqm', label: t('properties.form.metrics.livingArea') || 'Wohnfläche (m²)', type: 'number' },
    { section: sArea, key: 'usable_area_sqm', label: t('properties.form.metrics.usableArea') || 'Nutzfläche (m²)', type: 'number' },
    { section: sArea, key: 'plot_area_sqm', label: t('properties.form.metrics.plotArea') || 'Grundstücksfläche (m²)', type: 'number' },
    { section: sArea, key: 'ownership_share', label: t('properties.form.ownership.ownershipShare') || 'Eigentumsanteil (%)', type: 'number' },
    { section: sFin, key: 'purchase_price', label: t('properties.form.ownership.purchasePrice') || 'Kaufpreis (€)', type: 'number' },
    { section: sFin, key: 'purchase_date', label: t('properties.form.ownership.purchaseDate') || 'Kaufdatum', type: 'date' },
    { section: sFin, key: 'market_value', label: t('properties.form.ownership.marketValue') || 'Marktwert (€)', type: 'number' },
    { section: sFin, key: 'valuation_date', label: t('properties.form.ownership.valuationDate') || 'Bewertungsdatum', type: 'date' },
  ], [t, portfolios, sStamm, sAddr, sArea, sFin]);

  const invalidate = () => store?.invalidateRelated('properties', 'portfolios', 'units', 'contracts', 'maintenance', 'documents');
  const handleSave = async data => {
    requireWrite();
    if (modal === 'create') await api.post('/properties', data);
    else await api.put(`/properties/${modal.id}`, data);
  };

  const afterSave = () => {
    void refreshData();
    invalidate();
  };
  const handleDelete = async row => {
    if (!isAllowed() || busyId) return;
    if (!await confirm(`"${row.name}" ${t('modals.confirmDelete.body')}`)) return;
    setActionError(null);
    setBusyId(row.id);
    try {
      if (!isAllowed()) return;
      await api.del(`/properties/${row.id}`, revisionOptions(row));
      void refreshData();
      invalidate();
    } catch (err) { setActionError(err.message); }
    finally { setBusyId(null); }
  };

  return (
    <div className="page properties-page">
      <header className="property-page-heading">
        <div><span className="property-eyebrow">{t('properties.eyebrow')}</span><h1>{t('properties.list.title')}</h1><p>{t('properties.subtitle')}</p></div>
        {canWrite && <button className="btn btn-primary" onClick={() => setModal('create')} disabled={portfoliosData.loading || Boolean(portfoliosData.error) || !portfolios.length}><Plus size={18} aria-hidden="true" />{t('properties.create')}</button>}
      </header>

      {canWrite && !portfoliosData.loading && !portfoliosData.error && !portfolios.length && <div className="property-notice">{t('properties.needsPortfolio')} <Link to="/portfolios">{t('properties.managePortfolios')} <ArrowUpRight size={14} aria-hidden="true" /></Link></div>}
      <section className="property-metrics" aria-label={t('properties.summary')}>
        <div className="property-metric"><span>{t('properties.objects')}</span><strong>{loading || error ? '—' : count(enriched.length)}</strong><small>{t('properties.recordedProperties')}</small></div>
        <div className="property-metric"><span>{t('properties.units')}</span><strong>{loading || error || totalUnits == null ? '—' : count(totalUnits)}</strong><small>{t('properties.acrossProperties')}</small></div>
        <div className="property-metric"><span>{t('properties.occupancy')}</span><strong>{loading || error || occupancyRate == null ? '—' : `${occupancyRate}%`}</strong><small>{unitsReady && totalUnits > 0 ? t('properties.occupiedOf', { occupied: count(totalOccupied), total: count(totalUnits) }) : t('properties.unitBasis')}</small></div>
        <div className="property-metric"><span>{t('properties.vacantUnits')}</span><strong>{loading || error || !unitsReady ? '—' : count(enriched.reduce((sum, prop) => sum + prop.vacant_count, 0))}</strong><small>{t('properties.vacancyBasis')}</small></div>
      </section>

      {[['units', unitsData], ['maintenance', maintenanceData], ['portfolios', portfoliosData]].filter(([, data]) => data.error).map(([key, data]) => <div className="property-notice property-notice-error" role="alert" key={key}><div><strong>{t(`properties.errors.${key}`)}</strong><p>{data.error}</p></div><button className="btn btn-secondary btn-sm" onClick={data.reload}><RefreshCw size={15} aria-hidden="true" />{t('properties.retry')}</button></div>)}
      {actionError && <div className="property-notice property-notice-error" role="alert"><div><strong>{t('properties.actionFailed')}</strong><p>{actionError}</p></div><button className="btn btn-secondary btn-sm" onClick={() => setActionError(null)}>{t('properties.dismiss')}</button></div>}

      <section className="property-inventory" aria-label={t('properties.inventory')}>
        <div className="property-inventory-heading"><div><h2>{t('properties.inventory')}</h2><p role="status">{loading ? t('ui.table.loading') : error ? t('properties.errors.properties') : t('properties.results', { count: count(filtered.length), total: count(enriched.length) })}</p></div><button className="property-icon-button" aria-label={t('properties.refresh')} onClick={reloadAll} disabled={loading}><RefreshCw size={18} aria-hidden="true" /></button></div>
        <div className="property-toolbar">
          <label className="property-search"><Search size={18} aria-hidden="true" /><span className="property-sr-only">{t('properties.search')}</span><input type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder={t('properties.searchPlaceholder')} /></label>
          <label className="property-select"><span>{t('properties.portfolio')}</span><select value={portfolioFilter} onChange={event => setPortfolioFilter(event.target.value)} disabled={portfoliosData.loading || Boolean(portfoliosData.error)}><option value="">{t('properties.allPortfolios')}</option>{portfolios.map(portfolio => <option key={portfolio.id} value={portfolio.id}>{portfolio.name}</option>)}</select></label>
          <label className="property-select"><span>{t('properties.sort')}</span><select value={sort} onChange={event => setSort(event.target.value)}><option value="name">{t('properties.sortName')}</option><option value="city">{t('properties.sortCity')}</option><option value="rent">{t('properties.sortRent')}</option></select></label>
          <div className="property-view-switch" role="group" aria-label={t('properties.view')}><button aria-label={t('properties.cardView')} aria-pressed={view === 'cards'} onClick={() => setView('cards')}><LayoutGrid size={18} aria-hidden="true" /></button><button aria-label={t('properties.tableView')} aria-pressed={view === 'table'} onClick={() => setView('table')}><List size={18} aria-hidden="true" /></button></div>
        </div>
        <div className="property-filter-bar" role="group" aria-label={t('properties.filter')}>
          {['all', 'active', 'inactive', 'vacancy', 'open_maintenance'].map(key => <button className="property-filter" key={key} aria-pressed={filter === key} disabled={(key === 'vacancy' && !unitsReady) || (key === 'open_maintenance' && !maintenanceReady)} onClick={() => setFilter(key)}>{t(`properties.filters.${key}`)}</button>)}
          {hasFilters && <button className="property-reset" onClick={resetFilters}>{t('properties.reset')}</button>}
        </div>

        {loading && <div className="property-state" role="status"><div className="property-state-icon"><Building2 size={27} aria-hidden="true" /></div><h3>{t('properties.loading')}</h3><p>{t('properties.loadingDescription')}</p></div>}
        {!loading && error && <div className="property-state property-state-error" role="alert"><h3>{t('properties.errors.properties')}</h3><p>{error}</p><button className="btn btn-primary" onClick={refreshData}><RefreshCw size={16} aria-hidden="true" />{t('properties.retry')}</button></div>}
        {!loading && !error && !filtered.length && <div className="property-state"><div className="property-state-icon"><Building2 size={29} aria-hidden="true" /></div><h3>{t(hasFilters ? 'properties.noResults' : 'properties.emptyTitle')}</h3><p>{t(hasFilters ? 'properties.noResultsDescription' : 'properties.emptyDescription')}</p>{hasFilters ? <button className="btn btn-secondary" onClick={resetFilters}>{t('properties.reset')}</button> : canWrite && portfolios.length > 0 && <button className="btn btn-primary" onClick={() => setModal('create')}><Plus size={16} aria-hidden="true" />{t('properties.create')}</button>}</div>}
        {!loading && !error && filtered.length > 0 && view === 'cards' && <div className="property-card-grid">{filtered.map(prop => <article className="property-card" key={prop.id}>
          <div className="property-card-top"><div className="property-object-icon"><Building2 size={22} aria-hidden="true" /></div><PropertyStatus status={prop.status} t={t} /></div>
          <p className="property-card-context">{prop.portfolio_name} <span>·</span> {typeLabel(prop.property_type)}</p>
          <h3><Link to={`/properties/${prop.id}`}>{prop.name}<ArrowUpRight size={20} aria-hidden="true" /></Link></h3>
          <p className="property-card-address"><MapPin size={15} aria-hidden="true" /><span>{prop.address || t('properties.noAddress')}</span></p>
          <div className="property-card-metrics"><div><span>{t('properties.units')}</span><strong>{prop.unit_count ?? '—'}</strong></div><div><span>{t('properties.occupancy')}</span><strong>{prop.occupancy_rate == null ? '—' : `${prop.occupancy_rate}%`}</strong></div><div><span>{t('properties.monthlyRent')}</span><strong>{money(prop.total_rent)}</strong></div></div>
          <div className="property-occupancy-track" aria-hidden="true"><span style={{ width: `${prop.occupancy_rate ?? 0}%` }} /></div>
          <div className="property-card-bottom"><div className="property-card-signals">{unitsReady && prop.vacant_count > 0 && <span><Home size={14} aria-hidden="true" />{t('properties.vacancyCount', { count: prop.vacant_count })}</span>}{maintenanceReady && prop.open_maintenance > 0 && <span><Wrench size={14} aria-hidden="true" />{t('properties.maintenanceCount', { count: prop.open_maintenance })}</span>}{unitsReady && maintenanceReady && !prop.vacant_count && !prop.open_maintenance && <span>{t('properties.noOpenItems')}</span>}</div>{canWrite && <div className="property-card-actions"><button className="property-icon-button" aria-label={t('properties.editNamed', { name: prop.name })} onClick={() => setModal(prop)} disabled={Boolean(busyId)}><Pencil size={15} aria-hidden="true" /></button><button className="property-icon-button property-delete" aria-label={t('properties.deleteNamed', { name: prop.name })} onClick={() => handleDelete(prop)} disabled={Boolean(busyId)}><Trash2 size={15} aria-hidden="true" /></button></div>}</div>
        </article>)}</div>}
        {!loading && !error && filtered.length > 0 && view === 'table' && <DataTable title={t('properties.inventory')} columns={columns} data={filtered} onEdit={!canWrite ? undefined : row => setModal(row)} onDelete={!canWrite || busyId ? undefined : handleDelete} onRowClick={row => navigate(`/properties/${row.id}`)} />}
        {!loading && !error && filtered.length > 0 && <p className="property-data-caption">{t('properties.rentBasis')}</p>}
      </section>
      {modal && canWrite && <FormModal onSaved={afterSave} draftConfig={{ collection: 'properties' }} title={t(modal === 'create' ? 'properties.create' : 'properties.edit')} fields={fields} initial={modal === 'create' ? null : modal} onSave={handleSave} onClose={() => setModal(null)} />}
    </div>
  );
}
