import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { Check, CircleStop, RotateCcw } from 'lucide-react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';
import { useToast } from '../components/Toast';
import { useCanWrite } from '../contexts/AuthContext';
import { formatDate } from '../utils/format';
import { bulkDelete } from '../utils/bulkActions';
import { Copy as CopyIcon } from 'lucide-react';
import { duplicateOf } from '../utils/duplicate';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import ObjectScope from '../components/ObjectScope';
import { scopeDefaults } from '../utils/objectScope';
import RelatedPageLinks from '../components/RelatedPageLinks';
import useAssistantHandoff from '../hooks/useAssistantHandoff';
import AssistantHandoffNotice from '../components/AssistantHandoffNotice';
import KpiAction from '../components/KpiAction';
import InlineFieldEditor from '../features/workCenter/InlineFieldEditor';
import UndoNotice from '../features/workCenter/UndoNotice';
import TaskRecurrenceField from '../features/tasks/TaskRecurrenceField';
import { recurrenceError, recurrenceSummary } from '../features/tasks/taskRecurrence';
import '../features/workCenter/workCenter.css';

const isFinished = status => ['completed', 'cancelled', 'canceled', 'closed', 'done', 'archived'].includes(status);

function isOverdue(dueDate, status) {
  if (!dueDate || ['completed', 'cancelled', 'canceled', 'closed', 'done', 'archived'].includes(status)) return false;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const due = new Date(dueDate);
  due.setHours(0, 0, 0, 0);
  return due < today;
}

function isToday(dueDate) {
  if (!dueDate) return false;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const due = new Date(dueDate);
  due.setHours(0, 0, 0, 0);
  return due.getTime() === today.getTime();
}

function isWithinWeek(dueDate) {
  if (!dueDate) return false;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const due = new Date(dueDate);
  due.setHours(0, 0, 0, 0);
  const weekFromNow = new Date(today);
  weekFromNow.setDate(weekFromNow.getDate() + 7);
  return due >= today && due <= weekFromNow;
}

export default function Tasks() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const readFilter = () => {
    const value = params.get('status') || params.get('filter');
    return ['all', 'open', 'in_progress', 'completed', 'cancelled', 'today', 'week', 'overdue', 'recurring'].includes(value) ? value : 'all';
  };
  const { t } = useTranslation();
  const confirm = useConfirm();
  const toast = useToast();
  const canWrite = useCanWrite('/tasks');
  const store = useDataStore();
  const propertyState = useEntities('properties', '/properties');
  const unitState = useEntities('units', '/units');
  const properties = propertyState.items;
  const units = unitState.items;
  const choicesReady = !propertyState.loading && !unitState.loading && !propertyState.error && !unitState.error;

  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  // values of a duplicated task for the New form (null: an empty form)
  const [prefill, setPrefill] = useState(null);
  const assistantHandoff = useAssistantHandoff('task', values => { setPrefill(values); setModal('create'); });
  const assistantSaved = useRef(false);
  useEffect(() => { assistantSaved.current = false; }, [assistantHandoff.identifier]);
  const [quickChange, setQuickChange] = useState(null);
  const [filter, setFilter] = useState(readFilter);
  const [drilldown, setDrilldown] = useState(0);
  const openSources = key => {
    setFilter(key); setDrilldown(value => value + 1);
    setParams(current => { const next = new URLSearchParams(current); ['filter', 'status', 'focus_id', 'suche'].forEach(name => next.delete(name));
      if (key !== 'all') next.set(['open', 'in_progress', 'completed', 'cancelled'].includes(key) ? 'status' : 'filter', key);
      return next; });
  };
  const linkedFilter = readFilter();
  useEffect(() => { setFilter(linkedFilter); setDrilldown(value => value + 1); }, [linkedFilter, params]);
  const [loadError, setLoadError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [recurrenceErrors, setRecurrenceErrors] = useState([]);
  const [busy, setBusy] = useState(new Set());
  const busyRef = useRef(new Set());
  const loadRef = useRef(null);

  const noneOpt = t('pages.tasks.form.noneOption') || '— Keine —';

  const refreshData = useCallback(async () => {
    loadRef.current?.abort();
    const request = new AbortController();
    loadRef.current = request;
    setLoading(true);
    setLoadError(null);
    try {
      const data = await api.list('/tasks', { signal: request.signal });
      if (!Array.isArray(data)) throw new Error('Der Server hat keine gültige Aufgabenliste geliefert');
      if (!request.signal.aborted) {
        setTasks(data);
        return true;
      }
    } catch (err) {
      if (!request.signal.aborted) setLoadError(err.message);
    } finally {
      if (!request.signal.aborted) setLoading(false);
    }
    return false;
  }, []);

  useEffect(() => {
    refreshData();
    return () => loadRef.current?.abort();
  }, [refreshData]);

  // Lookup maps
  const propertyMap = Object.fromEntries(properties.map(p => [p.id, p.name]));
  const unitMap = Object.fromEntries(units.map(u => [u.id, u.label]));
  const unitProperties = Object.fromEntries(units.map(unit => [unit.id, unit.property_id]));

  // Enriched data
  const effectiveProperty = task => task.property_id || unitProperties[task.unit_id];
  const enriched = tasks.filter(task => (!params.get('property_id') || effectiveProperty(task) === params.get('property_id'))
    && (!params.get('unit_id') || task.unit_id === params.get('unit_id'))
    && (!params.get('parent_task_id') || task.parent_task_id === params.get('parent_task_id'))).map(task => ({
    ...task,
    property_id: effectiveProperty(task),
    property_name: propertyMap[effectiveProperty(task)] || '—',
    unit_label: unitMap[task.unit_id] || '—',
    is_overdue: isOverdue(task.due_date, task.status),
    recurrence_label: task.recurrence_rule ? recurrenceSummary(task.recurrence_rule, t) : '—',
  }));

  // Filtered data
  const filtered = useMemo(() => {
    switch (filter) {
      case 'open': return enriched.filter(t => t.status === 'open');
      case 'in_progress': case 'completed': case 'cancelled': return enriched.filter(t => t.status === filter);
      case 'today': return enriched.filter(t => isToday(t.due_date));
      case 'week': return enriched.filter(t => isWithinWeek(t.due_date));
      case 'overdue': return enriched.filter(t => t.is_overdue);
      case 'recurring': return enriched.filter(t => !!t.recurrence_rule);
      default: return enriched;
    }
  }, [enriched, filter]);

  // Summary stats
  const totalCount = enriched.length;
  const openCount = enriched.filter(t => t.status === 'open').length;
  const overdueCount = enriched.filter(t => t.is_overdue).length;
  const inProgressCount = enriched.filter(t => t.status === 'in_progress').length;
  const recurringCount = enriched.filter(t => !!t.recurrence_rule).length;

  const applyQuickChange = result => {
    if (!result?.record?.id) return;
    setTasks(current => current.map(task => task.id === result.record.id ? result.record : task));
    setQuickChange(result.undo_id ? result : null);
    store?.invalidateRelated('tasks');
  };
  const inline = (row, field, label, content, options, type) => <InlineFieldEditor record={row} field={field} label={label}
    options={options} type={type} canEdit={canWrite && !busy.has(row.id)} onSaved={applyQuickChange}>{content}</InlineFieldEditor>;
  const columns = [
    { key: 'title', label: t('pages.tasks.columns.title') || 'Titel', filterType: 'text', render: (value, row) =>
      <Link to={{ search: (() => { const next = new URLSearchParams(params); next.set('focus_id', row.id); return `?${next}`; })() }}>{value}</Link> },
    { key: 'property_name', hidden: true, label: t('portfolio.properties.form.name') || 'Immobilie', filterType: 'text' },
    { key: 'unit_label', subKey: 'property_name', label: t('units.list.columns.label') || 'Einheit', filterType: 'text', link: 'unit', subLink: 'property' },
    { key: 'assignee', label: t('pages.tasks.columns.assignee') || 'Zuständig', filterType: 'text',
      render: (value, row) => inline(row, 'assignee', 'Zuständig', value || '—') },
    { key: 'due_date', label: t('pages.tasks.columns.dueDate') || 'Fällig am', type: 'date', filterType: 'dateRange',
      render: (v, row) => {
        const display = v ? formatDate(v) : '—';
        return inline(row, 'due_date', 'Fällig am', isOverdue(v, row.status)
          ? <span style={{ color: 'var(--danger)', fontWeight: 700 }}>{display}</span> : display, undefined, 'date');
      }},
    { key: 'is_overdue', hidden: true, label: 'Überfällig',
      render: v => v ? <StatusBadge status="danger" label="Überfällig" /> : '—' },
    { key: 'recurrence_label', hidden: true, label: t('pages.tasks.form.recurrence') || 'Wiederholung', filterType: 'text' },
    { key: 'priority', label: t('pages.tasks.columns.priority') || 'Priorität', type: 'status', filterType: 'select',
      render: (value, row) => inline(row, 'priority', 'Priorität', <StatusBadge status={value} />, [
        { value: 'low', label: 'Niedrig' }, { value: 'medium', label: 'Mittel' }, { value: 'high', label: 'Hoch' }, { value: 'urgent', label: 'Dringend' },
      ]) },
    { key: 'status', label: t('pages.tasks.columns.status') || 'Status', type: 'status', filterType: 'select',
      render: (value, row) => inline(row, 'status', 'Status', <StatusBadge status={value} />, [
        { value: 'open', label: 'Offen' }, { value: 'in_progress', label: 'In Arbeit' },
        { value: 'completed', label: 'Erledigt' }, { value: 'cancelled', label: 'Abgebrochen' },
      ]) },
  ];

  const fields = [
    { key: 'title', label: t('pages.tasks.form.title') || 'Titel', required: true },
    { key: 'description', label: t('pages.tasks.form.description') || 'Beschreibung', type: 'textarea' },
    { key: 'assignee', label: t('pages.tasks.form.assignee') || 'Zuständig' },
    { key: 'property_id', label: t('pages.tasks.form.property') || 'Immobilie', type: 'select',
      clearOnChange: ['unit_id'],
      options: [{ value: '', label: noneOpt }, ...properties.map(p => ({ value: p.id, label: p.name }))] },
    { key: 'unit_id', label: t('pages.tasks.form.unit') || 'Einheit', type: 'select',
      options: values => [{ value: '', label: noneOpt }, ...units
        .filter(u => !values.property_id || u.property_id === values.property_id)
        .map(u => ({ value: u.id, label: values.property_id ? u.label : `${propertyMap[u.property_id] || 'Immobilie'} · ${u.label}` }))] },
    { key: 'due_date', label: t('pages.tasks.form.dueDate') || 'Fällig am', type: 'date' },
    { key: 'recurrence_rule', label: t('pages.tasks.form.recurrence') || 'Wiederholung', full: true,
      component: TaskRecurrenceField, validate: value => {
        const error = recurrenceError(value);
        return error ? t(`pages.tasks.recurrence.${error}`) : null;
      } },
    { key: 'priority', label: t('pages.tasks.form.priority') || 'Priorität', type: 'select', default: 'medium', options: [
      { value: 'low', label: t('pages.tasks.priority.low') || 'Niedrig' },
      { value: 'medium', label: t('pages.tasks.priority.medium') || 'Mittel' },
      { value: 'high', label: t('pages.tasks.priority.high') || 'Hoch' },
      { value: 'urgent', label: t('pages.tasks.priority.urgent') || 'Dringend' },
    ]},
    { key: 'status', label: t('pages.tasks.form.status') || 'Status', type: 'select', default: 'open', options: [
      { value: 'open', label: t('pages.tasks.status.open') || 'Offen' },
      { value: 'in_progress', label: t('pages.tasks.status.inProgress') || 'In Bearbeitung' },
      { value: 'completed', label: t('pages.tasks.status.completed') || 'Erledigt' },
      { value: 'cancelled', label: 'Abgebrochen / Serie beendet' },
    ]},
  ];

  const handleSave = async (data) => {
    if (!choicesReady) throw new Error('Bitte zuerst die Immobilien- und Einheitenauswahl erneut laden.');
    if (modal === 'create' && assistantHandoff.identifier) {
      await assistantHandoff.save(data);
      assistantSaved.current = true;
      store?.invalidateRelated('tasks');
      toast.success('Aufgabe gespeichert und mit dem Assistentenvorschlag verknüpft');
      return;
    }
    let saved;
    if (modal === 'create') {
      saved = await api.post('/tasks', data);
      setTasks(current => [...current, saved]);
    } else {
      saved = await api.patch(`/tasks/${modal.id}`, data);
      setTasks(current => current.map(row => row.id === saved.id ? saved : row));
    }
    setActionError(null);
    toast.success('Aufgabe gespeichert');
    refreshData();
    if (store) store.invalidateRelated('tasks', 'properties', 'units');
  };

  const handleDelete = async (row) => {
    if (!await confirm(`"${row.title || row.id}" ${t('modals.confirmDelete.body')}`, { action: 'delete' })) return;
    try {
      await api.del(`/tasks/${row.id}`);
      setTasks(current => current.filter(task => task.id !== row.id));
      setActionError(null);
      toast.success('Aufgabe gelöscht');
    } catch (err) {
      setActionError(err);
      toast.error(err.message);
      return;
    }
    refreshData();
    if (store) store.invalidateRelated('tasks', 'properties', 'units');
  };

  const runAction = async (key, action) => {
    if (busyRef.current.has(key)) return;
    busyRef.current.add(key);
    setBusy(new Set(busyRef.current));
    setActionError(null);
    try {
      await action();
    } catch (err) {
      setActionError(err);
      toast.error(err.message);
    } finally {
      busyRef.current.delete(key);
      setBusy(new Set(busyRef.current));
    }
  };

  const toggleCompleted = row => runAction(row.id, async () => {
    const status = isFinished(row.status) ? 'open' : 'completed';
    const saved = await api.patch(`/tasks/${row.id}`, { status, updated_at: row.updated_at });
    setTasks(current => current.map(task => task.id === row.id ? saved : task));
    toast.success(status === 'completed' ? 'Aufgabe erledigt' : 'Aufgabe wieder geöffnet');
    refreshData();
    store?.invalidateRelated('tasks');
  });

  const generateRecurring = () => runAction('recurrence', async () => {
    const report = await api.post('/tasks/generate-recurring/report', {});
    if (!Array.isArray(report?.created) || !Array.isArray(report?.errors)) throw new Error('Ungültige Antwort beim Erzeugen der Folgeaufgaben');
    setRecurrenceErrors(report.errors);
    setTasks(current => [...current, ...report.created]);
    toast.success(`${report.created.length} ${report.created.length === 1 ? 'Folgeaufgabe erzeugt' : 'Folgeaufgaben erzeugt'}`);
    refreshData();
    store?.invalidateRelated('tasks');
  });

  const lookupErrors = [propertyState.error, unitState.error].filter(Boolean);
  const selectedTask = enriched.find(row => row.id === params.get('focus_id'));
  const reloadAfterConflict = async () => {
    const conflict = actionError;
    // Refresh only the list; an open form keeps its draft and captured revision.
    if (await refreshData()) setActionError(current => current === conflict ? null : current);
  };
  const retry = () => {
    refreshData();
    if (propertyState.error) propertyState.reload();
    if (unitState.error) unitState.reload();
  };
  if (loading && tasks.length === 0 && !loadError && !modal) return <div className="page-loading">Lade Aufgaben...</div>;

  return (
    <div className="page">
      <div className="page-header">
        <h1>{t('pages.tasks.title') || 'Aufgaben'}</h1>
        {canWrite && <button className="btn btn-secondary" onClick={generateRecurring} disabled={busy.has('recurrence')}>Folgeaufgaben erzeugen</button>}
      </div>
      <ObjectScope params={params} setParams={setParams} properties={properties} units={units} />
      {params.get('parent_task_id') && <p className="filter-chips">Folgeaufgaben einer Serie{' '}
        <Link to={`/tasks?focus_id=${encodeURIComponent(params.get('parent_task_id'))}`}>Ausgangsaufgabe öffnen</Link>{' '}
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => setParams(current => {
          const next = new URLSearchParams(current); next.delete('parent_task_id'); next.delete('focus_id'); return next;
        })}>Serienfilter aufheben</button></p>}
      {selectedTask && <section className="card" aria-label="Aufgabendetails" style={{ padding: '1rem', marginBottom: '1rem' }}>
        <div className="page-header"><h2>{selectedTask.title}</h2>
          {canWrite && choicesReady && <button type="button" className="btn btn-secondary btn-sm" onClick={() => setModal(selectedTask)}>Aufgabe bearbeiten</button>}</div>
        <p><StatusBadge status={selectedTask.status} /> · Fällig: {formatDate(selectedTask.due_date)} · Zuständig: {selectedTask.assignee || 'Nicht zugewiesen'}</p>
        {selectedTask.description && <p style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{selectedTask.description}</p>}
        {selectedTask.recurrence_rule && <p>{selectedTask.recurrence_label}{' '}
          {['cancelled', 'canceled', 'archived'].includes(selectedTask.status) && '– Serie beendet; bestehende Folgeaufgaben bleiben erhalten.'}</p>}
        <RelatedPageLinks items={[
          ...(selectedTask.property_id ? [{ to: `/properties/${encodeURIComponent(selectedTask.property_id)}`, label: selectedTask.property_name }] : []),
          ...(selectedTask.unit_id ? [{ to: `/units/${encodeURIComponent(selectedTask.unit_id)}`, label: selectedTask.unit_label }] : []),
          ...(selectedTask.parent_task_id ? [{ to: `/tasks?focus_id=${encodeURIComponent(selectedTask.parent_task_id)}`, label: 'Ausgangsaufgabe' }] : []),
          ...(selectedTask.recurrence_rule && !selectedTask.parent_task_id ? [{ to: `/tasks?parent_task_id=${encodeURIComponent(selectedTask.id)}`, label: 'Alle Folgeaufgaben' }] : []),
        ]} />
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setParams(current => { const next = new URLSearchParams(current); next.delete('focus_id'); return next; })}>Detailansicht schließen</button>
      </section>}
      <AssistantHandoffNotice handoff={assistantHandoff} onClose={() => { setModal(null); setPrefill(null); assistantHandoff.clear(); }} />
      {quickChange && <UndoNotice key={quickChange.undo_id} change={quickChange} onDismiss={() => setQuickChange(null)} onUndone={applyQuickChange} />}
      {(loadError || lookupErrors.length > 0) && <div className="alert-error" role="alert">
        {[loadError, ...lookupErrors].filter(Boolean).join(' · ')}{' '}
        <button className="btn btn-secondary btn-sm" onClick={retry} disabled={loading}>Erneut laden</button>
      </div>}
      {actionError && <div className="alert-error" role="alert">
        {actionError.message}{' '}
        {actionError.statusCode === 409 && <button className="btn btn-secondary btn-sm" onClick={reloadAfterConflict} disabled={loading}>Aufgaben neu laden</button>}
      </div>}
      {recurrenceErrors.length > 0 && <div className="alert-error" role="alert">
        <p>Diese Serien konnten nicht fortgesetzt werden:</p>
        <ul>{recurrenceErrors.map(error => <li key={error.task_id}>{error.title}: {error.error}</li>)}</ul>
      </div>}
      {loading && tasks.length > 0 && <p role="status">Aufgaben werden aktualisiert…</p>}

      {/* Summary cards */}
      <div className="kpi-row">
        <KpiAction label="Gesamt" value={loadError && !tasks.length ? '—' : totalCount} onClick={() => openSources('all')} />
        <KpiAction label="Offen" value={loadError && !tasks.length ? '—' : openCount} color="var(--info)" onClick={() => openSources('open')} />
        <KpiAction label="Überfällig" value={loadError && !tasks.length ? '—' : overdueCount} color={overdueCount ? 'var(--danger)' : undefined} onClick={() => openSources('overdue')} />
        <KpiAction label="In Bearbeitung" value={loadError && !tasks.length ? '—' : inProgressCount} color="var(--warning)" onClick={() => openSources('in_progress')} />
        <KpiAction label="Wiederkehrend" value={loadError && !tasks.length ? '—' : recurringCount} onClick={() => openSources('recurring')} />
      </div>

      {/* Filter tabs */}
      <div className="filter-chips">
        {[
          { key: 'all', label: 'Alle' },
          { key: 'open', label: 'Offen' },
          { key: 'in_progress', label: 'In Bearbeitung' },
          { key: 'completed', label: 'Erledigt' },
          { key: 'cancelled', label: 'Abgebrochen' },
          { key: 'today', label: 'Heute' },
          { key: 'week', label: 'Diese Woche' },
          { key: 'overdue', label: 'Überfällig' },
          { key: 'recurring', label: 'Wiederkehrend' },
        ].map(f => (
          <button
            key={f.key}
            className={`btn btn-sm ${filter === f.key ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => openSources(f.key)}
          >{f.label}</button>
        ))}
      </div>

      <DataTable
        title={t('pages.tasks.title') || 'Aufgaben'}
        columns={columns}
        data={filtered}
        clearFocusedRow={() => setParams(current => { const next = new URLSearchParams(current); next.delete('focus_id'); return next; })}
        drilldownKey={drilldown}
        viewConfig={{ column_filters: { workflow_filter: filter, property_id: params.get('property_id') || '', unit_id: params.get('unit_id') || '' } }}
        onApplyView={config => { const saved = config.column_filters || {}; setFilter(['all', 'open', 'in_progress', 'completed', 'cancelled', 'today', 'week', 'overdue', 'recurring'].includes(saved.workflow_filter) ? saved.workflow_filter : 'all');
          setParams(current => { const next = new URLSearchParams(current); ['status', 'filter', 'focus_id', 'suche'].forEach(key => next.delete(key));
            if (saved.workflow_filter && saved.workflow_filter !== 'all') next.set('filter', saved.workflow_filter);
            ['property_id', 'unit_id'].forEach(key => { if (saved[key]) next.set(key, saved[key]); else next.delete(key); }); return next; }); }}
        onAdd={choicesReady ? values => { setPrefill({ ...scopeDefaults(params, units), ...values }); setModal('create'); } : undefined}
        onEdit={choicesReady ? row => setModal(row) : undefined}
        onDelete={handleDelete}
        writeArea="/tasks"
        rowName={row => row.title || row.id}
        bulkActions={[
          { key: 'complete', label: 'Erledigen', write: true, applies: row => !isFinished(row.status),
            run: row => api.patch(`/tasks/${row.id}`, { status: 'completed', updated_at: row.updated_at }),
            finished: ({ succeeded }) => { if (succeeded.length) toast.success(`${succeeded.length} ${succeeded.length === 1 ? 'Aufgabe erledigt' : 'Aufgaben erledigt'}`); refreshData(); store?.invalidateRelated('tasks'); } },
          { key: 'reopen', label: 'Wiederöffnen', write: true, applies: row => isFinished(row.status),
            run: row => api.patch(`/tasks/${row.id}`, { status: 'open', updated_at: row.updated_at }),
            finished: () => { refreshData(); store?.invalidateRelated('tasks'); } },
          bulkDelete({ one: 'Aufgabe', many: 'Aufgaben', remove: row => api.del(`/tasks/${row.id}`),
            finished: () => { refreshData(); store?.invalidateRelated('tasks', 'properties', 'units'); } }),
        ]}
        rowActions={row => busy.has(row.id) ? [] : [{
          label: 'Duplizieren', write: true, icon: <CopyIcon size={15} />,
          onClick: () => { setPrefill(duplicateOf(row, ['status', 'completed_at', 'generated_from_task_id', 'occurrence_date'])); setModal('create'); },
        }, {
          label: isFinished(row.status) ? 'Wiederöffnen' : 'Erledigen', write: true,
          icon: isFinished(row.status) ? <RotateCcw size={15} /> : <Check size={15} />,
          onClick: toggleCompleted,
        }, ...(row.recurrence_rule && !row.parent_task_id && !['cancelled', 'canceled', 'archived'].includes(row.status) ? [{
          label: 'Serie beenden', write: true, icon: <CircleStop size={15} />, onClick: () => runAction(row.id, async () => {
            if (!await confirm('Die Serie beenden? Es werden keine neuen Folgeaufgaben erzeugt. Bereits angelegte Aufgaben bleiben erhalten.')) return;
            const saved = await api.patch(`/tasks/${row.id}`, { status: 'cancelled', updated_at: row.updated_at });
            setTasks(current => current.map(task => task.id === row.id ? saved : task));
            refreshData(); store?.invalidateRelated('tasks'); toast.success('Aufgabenserie beendet');
          }),
        }] : [])]}
      />

      {modal && (
        <FormModal
          title={modal === 'create' ? 'Aufgabe erstellen' : 'Aufgabe bearbeiten'}
          repeatKeep={assistantHandoff.identifier ? undefined : ['assignee', 'property_id', 'due_date', 'priority', 'status']}
          fields={fields}
          initial={modal === 'create' ? prefill : modal}
          onSave={handleSave}
          onClose={() => { setModal(null); setPrefill(null);
            if (assistantSaved.current) { assistantSaved.current = false; navigate(assistantHandoff.returnHref); }
            else if (assistantHandoff.identifier) assistantHandoff.clear(); }}
        />
      )}
    </div>
  );
}
