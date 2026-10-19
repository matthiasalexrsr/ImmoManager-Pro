import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api';
import DataTable from '../components/DataTable';
import { useCanWrite } from '../contexts/AuthContext';
import { useToast } from '../components/Toast';
import { codeLabel } from '../utils/codeLabels';
import { formatDate, formatDateTime, formatMoney, formatNumber } from '../utils/format';
import { PROJECT_STATUS, STEP_TAB } from '../features/reletting/relettingModel';
import '../features/reletting/reletting.css';

// Neuvermietung: every vacant unit as a project, from the offer to the new tenancy.
export default function Reletting() {
  const navigate = useNavigate();
  const toast = useToast();
  const canWrite = useCanWrite('/reletting');
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [revision, setRevision] = useState(0);
  const [starting, setStarting] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    api.get('/reletting', { signal: controller.signal }).then(setData)
      .catch(failure => { if (!controller.signal.aborted) setError(failure.message); });
    return () => controller.abort();
  }, [revision]);

  const start = async row => {
    setStarting(row.unit_id);
    try {
      const created = await api.post('/reletting', { unit_id: row.unit_id });
      if (created.adopted) {
        toast.success(`${created.adopted} bereits erfasste${created.adopted === 1 ? ' Anfrage gehört' : ' Anfragen gehören'} jetzt zum Projekt.`);
      }
      navigate(`/reletting/${encodeURIComponent(created.project.id)}`);
    } catch (failure) {
      toast.error(failure.message);
      setStarting(null);
    }
  };

  if (error) return <div className="page"><div role="alert" className="alert alert-error">{error}
    <button type="button" className="btn btn-sm btn-secondary" onClick={() => setRevision(v => v + 1)}>Erneut laden</button></div></div>;
  if (!data) return <div className="page-loading" role="status">Neuvermietung wird geladen …</div>;

  const totals = data.totals;
  // the next step as text (search, filter and CSV), with where it is done
  const projects = data.projects.map(row => ({ ...row, next_step: row.next_step?.label || '', next_key: row.next_step?.key,
    next_detail: row.next_step?.detail }));
  const projectColumns = [
    { key: 'unit_label', label: 'Einheit', filterType: 'text',
      render: (value, row) => <Link to={row.href}>{value || '—'}</Link> },
    { key: 'property_name', label: 'Objekt', filterType: 'text',
      render: (value, row) => (row.property_id ? <Link to={`/properties/${encodeURIComponent(row.property_id)}`}>{value}</Link> : value || '—') },
    { key: 'status', label: 'Status', filterType: 'select',
      render: value => <span className={`badge ${PROJECT_STATUS[value]?.badge || 'badge-gray'}`}>{PROJECT_STATUS[value]?.label || codeLabel(value)}</span> },
    { key: 'next_step', label: 'Nächster Schritt', filterType: 'select', wrap: true,
      render: (value, row) => (value ? <><Link to={`${row.href}?tab=${STEP_TAB[row.next_key]}`}>{value}</Link>
        <div className="td-sub">{row.next_detail}</div></> : '—') },
    { key: 'available_from', label: 'Bezugsfrei ab', type: 'date', render: value => formatDate(value) },
    { key: 'warm_rent', label: 'Warmmiete', type: 'number', align: 'right', render: value => (value == null ? '—' : formatMoney(value)) },
    { key: 'applicants', label: 'Bewerbungen', type: 'number', align: 'right' },
    { key: 'next_viewing', label: 'Nächste Besichtigung', render: value => formatDateTime(value) },
    { key: 'accepted', label: 'Neuer Mieter', render: value => value || '—' },
    { key: 'purge_due', label: 'Zu löschen', type: 'number', align: 'right',
      render: value => (value ? <span className="badge badge-yellow" title="Absage liegt länger als drei Monate zurück">{value}</span> : '—') },
  ];
  const vacancyColumns = [
    { key: 'unit_label', label: 'Einheit', filterType: 'text', render: (value, row) => <Link to={row.href}>{value}</Link> },
    { key: 'property_name', label: 'Objekt', filterType: 'text',
      render: (value, row) => <Link to={`/properties/${encodeURIComponent(row.property_id)}`}>{value}</Link> },
    { key: 'unit_type', label: 'Art', render: value => codeLabel(value) || '—' },
    { key: 'area_sqm', label: 'Fläche', type: 'number', align: 'right', render: value => (value ? `${formatNumber(value, 1)} m²` : '—') },
    { key: 'rooms', label: 'Zimmer', type: 'number', align: 'right', render: value => (value ? formatNumber(value, 1) : '—') },
    { key: 'cold_rent', label: 'Bisherige Kaltmiete', type: 'number', align: 'right', render: value => (value ? formatMoney(value) : '—') },
    { key: 'vacant_since', label: 'Frei', render: (value, row) => (row.free_from ? `ab ${formatDate(row.free_from)} (Mietende)`
      : value ? `seit ${formatDate(value)}` : 'ohne Mietvertrag') },
    ...(canWrite ? [{ key: 'start', label: '', sortable: false, render: (_, row) => (
      <button type="button" className="btn btn-sm btn-primary" disabled={starting === row.unit_id} onClick={() => start(row)}>
        {starting === row.unit_id ? 'Wird angelegt …' : 'Neuvermietung starten'}</button>) }] : []),
  ];

  return (
    <div className="page reletting-hub">
      <p className="text-muted reletting-intro">Jede frei werdende Einheit als Projekt: Angebot und Exposé, Interessenten und
        Besichtigungen, Vergleich nach einheitlichen Kriterien, Übernahme in den Mietvertrag und das Löschen der übrigen
        Bewerberdaten. Es wird nichts automatisch versendet.</p>
      <div className="stats-grid">
        <div className="stat-card"><div className="stat-label">Laufende Projekte</div><div className="stat-value">{totals.open}</div></div>
        <div className="stat-card"><div className="stat-label">Frei ohne Projekt</div><div className="stat-value">{totals.vacant_without_project}</div></div>
        <div className="stat-card"><div className="stat-label">Offene Bewerbungen</div><div className="stat-value">{totals.applicants}</div></div>
        <div className="stat-card"><div className="stat-label">Bewerberdaten zu löschen</div>
          <div className="stat-value">{totals.purge_due}</div>
          {totals.purge_due > 0 && <div className="text-muted reletting-small">Absage länger als drei Monate her</div>}</div>
      </div>
      <DataTable title="Neuvermietungsprojekte" columns={projectColumns} data={projects} writeArea="/reletting"
        onRowClick={row => navigate(row.href)} emptyText="Noch kein Projekt. Unten eine freie Einheit wählen und die Neuvermietung starten." />
      <DataTable title="Freie und frei werdende Einheiten" columns={vacancyColumns} data={data.vacancies} writeArea="/reletting"
        settingsKey="reletting-vacancies"
        emptyText="Keine freie Einheit ohne Projekt. Einheiten, deren Mietvertrag in den nächsten vier Monaten endet, erscheinen hier ebenfalls." />
    </div>
  );
}
