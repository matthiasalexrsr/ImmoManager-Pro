import { useState, useEffect } from 'react';
import { Calculator } from 'lucide-react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import KpiAction from '../components/KpiAction';
import FormModal from '../components/FormModal';
import { useConfirm } from '../components/ConfirmDialog';
import { formatDate, formatMoney } from '../utils/format';

function fmt(v) {
  return new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' }).format(v || 0);
}

const CATEGORY_OPTIONS = [
  { value: 'maintenance', label: 'Instandhaltung' },
  { value: 'operating_costs', label: 'Betriebskosten' },
  { value: 'renovation', label: 'Renovierung' },
  { value: 'reserve', label: 'Rücklage' },
  { value: 'other', label: 'Sonstiges' },
];

// income and the owners' own money are no spending (services/budget_actuals.py)
const NOT_SPENDING = new Set(['income', 'private']);

/** The booking categories whose expenses make up the actual amount when it is taken from the bookings. */
function bookingCategoryField(categories, portfolios) {
  const names = Object.fromEntries(portfolios.map(p => [p.id, p.name]));
  const spending = categories.filter(c => !NOT_SPENDING.has(c.category_type));
  return function BookingCategories({ id, value, onChange, disabled }) {
    const chosen = new Set(Array.isArray(value) ? value : []);
    const toggle = categoryId => {
      const next = new Set(chosen);
      if (next.has(categoryId)) next.delete(categoryId); else next.add(categoryId);
      onChange([...next]);
    };
    if (!spending.length) return <p id={id} className="text-muted">Noch keine Ausgabenkategorien angelegt.</p>;
    return (
      <fieldset id={id} className="checkbox-list" disabled={disabled}>
        {spending.map(c => (
          <label key={c.id}>
            <input type="checkbox" checked={chosen.has(c.id)} onChange={() => toggle(c.id)} />
            {c.name}{portfolios.length > 1 && names[c.portfolio_id] ? ` (${names[c.portfolio_id]})` : ''}
          </label>
        ))}
      </fieldset>
    );
  };
}

const COLUMNS = [
  { key: 'property_name', label: 'Immobilie', filterType: 'text', link: 'property' },
  { key: 'year', label: 'Jahr', filterType: 'select' },
  { key: 'category', label: 'Kategorie', filterType: 'select',
    render: v => {
      const labels = { maintenance: 'Instandhaltung', operating_costs: 'Betriebskosten', renovation: 'Renovierung', reserve: 'Rücklage', other: 'Sonstiges' };
      return labels[v] || v;
    }},
  { key: 'planned_amount', label: 'Geplant (€)', type: 'number', sum: true, align: 'right',
    render: v => fmt(v) },
  { key: 'actual_amount', label: 'Tatsächlich (€)', type: 'number', sum: true, align: 'right',
    render: v => fmt(v) },
  { key: 'variance', label: 'Abweichung (€)', type: 'number', align: 'right',
    render: (v) => {
      const cls = v > 0 ? 'text-red' : v < 0 ? 'text-green' : '';
      return <span className={cls}>{fmt(v)}</span>;
    }},
];

export default function Budgets() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const { items: properties } = useEntities('properties', '/properties');
  const { items: categories } = useEntities('categories', '/categories');
  const { items: portfolios } = useEntities('portfolios', '/portfolios');
  const [actual, setActual] = useState(null);
  const [budgets, setBudgets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const [modal, setModal] = useState(null);
  const [deleteError, setDeleteError] = useState(null);
  const [drilldown, setDrilldown] = useState(0);
  const showSources = () => setDrilldown(value => value + 1);

  const refreshData = () => {
    setLoadError(null);
    api.list('/budgets')
      .then(b => { if (!Array.isArray(b)) throw new Error('Budgets konnten nicht gelesen werden.'); setBudgets(b); })
      .catch(e => setLoadError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    let cancelled = false;
    setLoadError(null); setLoading(true);
    api.list('/budgets')
      .then(data => { if (!Array.isArray(data)) throw new Error('Budgets konnten nicht gelesen werden.'); if (!cancelled) setBudgets(data); })
      .catch(e => { if (!cancelled) setLoadError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [attempt]);

  const propMap = Object.fromEntries(properties.map(p => [p.id, p]));
  const enriched = budgets.map(b => ({
    ...b,
    property_name: propMap[b.property_id]?.name || '—',
    variance: (b.actual_amount || 0) - (b.planned_amount || 0),
  }));

  const totalPlanned = enriched.reduce((s, b) => s + Math.round(Number(b.planned_amount || 0) * 100), 0) / 100;
  const totalActual = enriched.reduce((s, b) => s + Math.round(Number(b.actual_amount || 0) * 100), 0) / 100;

  const fields = [
    { key: 'property_id', label: 'Immobilie', required: true, type: 'select',
      options: properties.map(p => ({ value: p.id, label: p.name })) },
    { key: 'year', label: 'Jahr', type: 'number', required: true },
    { key: 'category', label: 'Kategorie', type: 'select', required: true, options: CATEGORY_OPTIONS },
    { key: 'planned_amount', label: 'Geplanter Betrag (€)', type: 'number', required: true },
    { key: 'actual_amount', label: 'Tatsächlicher Betrag (€)', type: 'number' },
    { key: 'booking_category_ids', label: 'Ist aus Buchungen dieser Kategorien', full: true,
      component: bookingCategoryField(categories, portfolios),
      hint: 'Optional. Über „Ist aus Buchungen“ lässt sich der tatsächliche Betrag dann aus den Ausgaben der Immobilie im Budgetjahr berechnen und übernehmen.' },
    { key: 'notes', label: 'Notizen', type: 'textarea' },
  ];

  const openActual = async row => {
    setActual({ row, loading: true });
    try {
      setActual({ row, result: await api.get(`/budgets/${row.id}/actual-from-bookings`) });
    } catch (err) {
      setActual({ row, error: err.message || 'Das Ist ließ sich nicht berechnen.' });
    }
  };

  const takeActual = async () => {
    setActual(current => ({ ...current, saving: true, error: null }));
    try {
      await api.post(`/budgets/${actual.row.id}/actual-from-bookings`, { expected_amount: actual.result.from_bookings });
      setActual(null);
      refreshData();
      if (store) store.invalidateRelated('budgets');
    } catch (err) {
      setActual(current => ({ ...current, saving: false, error: err.message || 'Übernehmen fehlgeschlagen' }));
    }
  };

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/budgets', data);
    } else {
      await api.put(`/budgets/${modal.id}`, data);
    }
    refreshData();
    if (store) store.invalidateRelated('budgets');
  };

  const handleDelete = async (row) => {
    if (!await confirm(`"${row.property_name} ${row.year}" ${t('modals.confirmDelete.body')}`, { action: 'delete' })) return;
    setDeleteError(null);
    try {
      await api.del(`/budgets/${row.id}`);
      refreshData();
      if (store) store.invalidateRelated('budgets');
    } catch (err) {
      setDeleteError(err.message || 'Löschen fehlgeschlagen');
    }
  };

  if (loading && !modal) return <div className="page-loading">{t('ui.table.loading')}</div>;
  if (loadError && !modal) return <div className="page"><div className="alert alert-error" role="alert">{loadError}<button type="button" className="btn btn-secondary" onClick={() => setAttempt(value => value + 1)}>Erneut laden</button></div></div>;

  return (
    <div className="page">
      <div className="stats-grid" style={{ marginBottom: '1rem' }}>
        <KpiAction label="Geplant gesamt" value={fmt(totalPlanned)} onClick={showSources} />
        <KpiAction label="Tatsächlich gesamt" value={fmt(totalActual)} onClick={showSources} />
        <KpiAction label="Abweichung" value={fmt(totalActual - totalPlanned)} onClick={showSources} />
      </div>
      <p className="text-muted">Grundlage: die geplanten und erfassten Istbeträge der unten aufgeführten Budgetpositionen. Mit gewählten Buchungskategorien berechnet „Ist aus Buchungen“ den Istbetrag auf Wunsch aus den Ausgaben.</p>

      {deleteError && (
        <div className="alert alert-error" style={{ marginBottom: '1rem' }}>
          {deleteError}
          <button onClick={() => setDeleteError(null)} style={{ marginLeft: '1rem', cursor: 'pointer' }}>✕</button>
        </div>
      )}
      <DataTable
        title="Budgets"
        columns={COLUMNS}
        data={enriched}
        drilldownKey={drilldown}
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
        rowActions={() => [{ label: 'Ist aus Buchungen', icon: <Calculator size={15} aria-hidden="true" />, write: true,
          onClick: openActual }]}
      />
      {actual && (
        <div className="modal-overlay" onClick={() => setActual(null)} role="presentation">
          <div className="modal modal-wide" role="dialog" aria-modal="true" aria-label="Ist aus Buchungen" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Ist aus Buchungen: {actual.row.property_name} {actual.row.year}</h2>
              <button onClick={() => setActual(null)} className="btn-close" aria-label="Schließen">✕</button>
            </div>
            <div className="modal-body">
              {actual.loading && <p>{t('ui.table.loading')}</p>}
              {actual.error && <div className="alert alert-error" role="alert">{actual.error}</div>}
              {actual.result && (<>
                <p>
                  Ausgaben {actual.result.year} in {actual.result.categories.map(c => `„${c.name}“`).join(', ')}:{' '}
                  <strong>{formatMoney(actual.result.from_bookings)}</strong>. Erfasst ist {formatMoney(actual.result.actual_amount)}
                  {actual.result.difference ? ` (Abweichung ${formatMoney(actual.result.difference)})` : ' – das stimmt überein'}.
                </p>
                {actual.result.bookings.length > 0 ? (
                  <table className="data-table">
                    <thead><tr><th>Datum</th><th>Kategorie</th><th>Text</th><th className="text-right">Betrag</th></tr></thead>
                    <tbody>
                      {actual.result.bookings.map(b => (
                        <tr key={b.id}>
                          <td>{formatDate(b.booking_date)}</td>
                          <td>{b.category}</td>
                          <td>{b.reverses_booking_id ? 'Storno' : (b.payment_text || '—')}</td>
                          <td className="text-right td-num">{formatMoney(b.amount)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : <p className="text-muted">Keine Buchungen dieser Kategorien im Budgetjahr.</p>}
                <div className="modal-footer">
                  <button type="button" className="btn btn-secondary" onClick={() => setActual(null)}>Abbrechen</button>
                  <button type="button" className="btn btn-primary" onClick={takeActual}
                    disabled={actual.saving || !actual.result.difference}>Als tatsächlichen Betrag übernehmen</button>
                </div>
              </>)}
            </div>
          </div>
        </div>
      )}
      {modal && (
        <FormModal
          title={modal === 'create' ? 'Budget erstellen' : 'Budget bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
