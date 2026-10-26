import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import useEffectiveSettings from '../../hooks/useEffectiveSettings';
import { useAuth } from '../../contexts/AuthContext';
import { useEntities, useDataStore } from '../../contexts/DataStoreContext';
import { formatDate } from '../../utils/format';
import { mayWrite } from '../../utils/permissions';
import EntityShelf from './EntityShelf';
import FeedState from './FeedState';
import useCursorFeed from './useCursorFeed';
import InlineFieldEditor from './InlineFieldEditor';
import UndoNotice from './UndoNotice';
import DeferralControl from './DeferralControl';
import WorkSummary from './WorkSummary';
import ConversationDialog from './ConversationDialog';
import NotificationInbox from '../../components/NotificationInbox';
import StatusBadge from '../../components/StatusBadge';
import NamedViews from '../../components/NamedViews';
import './workCenter.css';

const LABELS = { task: 'Aufgaben', maintenance: 'Instandhaltung', invoice: 'Rechnungen',
  document: 'Dokumente', receivable: 'Forderungen', dunning: 'Mahnvorgänge', contract: 'Fehlende Vertragsunterlagen',
  service_contract: 'Kündigungsfristen', meter: 'Zählerprüfungen', meter_reading: 'Fehlende Ablesungen im Abrechnungszeitraum', tenant_change: 'Offene Übergaben', contract_end: 'Mietwechsel', e_invoice: 'E-Rechnungseingänge' };
const today = () => { const date = new Date(); return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`; };

export default function WorkCenter() {
  const [params, setParams] = useSearchParams();
  const auth = useAuth();
  const { prefs, error: settingsError } = useEffectiveSettings(params.get('property_id'));
  const store = useDataStore();
  const { items: properties, error: propertyError, reload: reloadProperties } = useEntities('properties', '/properties');
  const [change, setChange] = useState(null);
  const [summaryRevision, setSummaryRevision] = useState(0);
  const [conversation, setConversation] = useState(null);
  const [inboxExpanded, setInboxExpanded] = useState(false);
  const query = new URLSearchParams();
  ['kind', 'property_id', 'due_before', 'deferred'].forEach(key => { if (params.get(key)) query.set(key, params.get(key)); });
  query.set('limit', '25');
  const feed = useCursorFeed(`/work-center/items?${query}`);
  const summaryQuery = new URLSearchParams(query); summaryQuery.delete('limit');
  const filter = (key, value) => setParams(current => { const next = new URLSearchParams(current); if (value) next.set(key, value); else next.delete(key); return next; });
  const refresh = updateItem => { setSummaryRevision(value => value + 1); feed.retry(updateItem); };
  const taskChanged = result => {
    store?.invalidateRelated('tasks');
    refresh(item => item.kind === 'task' && item.entity_id === result.record?.id
      ? { ...item, status: result.record.status, due_date: result.record.due_date,
        assignee: result.record.assignee, revision: result.record.updated_at } : item);
  };
  const changed = result => { setChange(result); taskChanged(result); };
  return <div className="page work-center">
    <header className="work-center-header"><div><h1>Arbeitszentrale</h1><p>Offene Vorgänge, persönliche Wiedervorlagen und Ihre zuletzt verwendeten Akten.</p></div>
      <Link className="btn btn-secondary" to="/review">Prüfliste öffnen</Link></header>
    <details onToggle={event => setInboxExpanded(event.currentTarget.open)}>
      <summary>Persönliche Benachrichtigungen und Archiv</summary>
      {inboxExpanded && <NotificationInbox compact />}
    </details>
    {settingsError && <p role="alert">{settingsError}</p>}
    {propertyError && <p role="alert">Die Immobilienauswahl konnte nicht geladen werden: {propertyError} <button type="button" className="btn btn-secondary btn-sm" onClick={reloadProperties}>Immobilien erneut laden</button></p>}
    <EntityShelf />
    <WorkSummary query={summaryQuery.toString()} revision={summaryRevision} />
    <section aria-label="Offene Vorgänge">
      <div className="work-center-toolbar">
      <div className="work-center-filters">
        <label>Bereich<select aria-label="Bereich" value={params.get('kind') || ''} onChange={event => filter('kind', event.target.value)}><option value="">Alle Bereiche</option>
          {Object.entries(LABELS).map(([value, label]) => <option value={value} key={value}>{label}</option>)}
        </select></label>
        <label>Immobilie<select aria-label="Immobilie" value={params.get('property_id') || ''} onChange={event => filter('property_id', event.target.value)}><option value="">Alle Immobilien</option>
          {properties.map(property => <option key={property.id} value={property.id}>{property.name}</option>)}
        </select></label>
        <label>Wiedervorlagen<select aria-label="Wiedervorlagen" value={params.get('deferred') || ''} onChange={event => filter('deferred', event.target.value)}>
          <option value="">Alle Vorgänge</option><option value="due">Wiedervorlage erreicht</option><option value="active">Jetzt bearbeiten (ohne zurückgestellte)</option>
        </select></label>
        <label className="work-center-date">Fällig bis<input type="date" value={params.get('due_before') || ''} onChange={event => filter('due_before', event.target.value)} /></label>
        <button type="button" className="btn btn-secondary" onClick={() => filter('due_before', today())}>Heute und überfällig</button>
        <button type="button" className="btn btn-secondary" disabled={!prefs} onClick={() => {
          const horizon = new Date(); horizon.setDate(horizon.getDate() + Number(prefs?.reminder_days || 0));
          filter('due_before', `${horizon.getFullYear()}-${String(horizon.getMonth() + 1).padStart(2, '0')}-${String(horizon.getDate()).padStart(2, '0')}`);
        }}>Mein Erinnerungsvorlauf ({prefs?.reminder_days || 0} Tage)</button>
        <button type="button" className="btn btn-ghost" onClick={() => setParams({})}>Filter zurücksetzen</button>
      </div>
      <NamedViews context="work-center" config={{ column_filters: Object.fromEntries(summaryQuery) }} onApply={config => {
        const filters = config.column_filters || {};
        const next = new URLSearchParams();
        ['kind', 'property_id', 'due_before', 'deferred'].forEach(key => { if (typeof filters[key] === 'string' && filters[key]) next.set(key, filters[key]); });
        setParams(next);
      }} />
      </div>
      {change && <UndoNotice key={change.undo_id} change={change} onDismiss={() => setChange(null)} onUndone={result => { setChange(null); taskChanged(result); }} />}
      <ul className="work-item-list">{feed.items.map(item => <li className="work-item" key={item.work_item_key}>
        <div className="work-item-heading"><h3><Link to={item.href}>{item.title}</Link></h3><span className="work-item-context">{LABELS[item.kind] || item.kind}</span></div>
        {item.subtitle && <p>{item.subtitle}</p>}
        {item.workflow && <div className="work-guidance">
          <p><strong>Nächster Schritt: </strong>{item.workflow.next_action.label}</p>
          {!item.workflow.next_action.allowed && item.workflow.next_action.reason && <p>{item.workflow.next_action.reason}</p>}
          {item.workflow.assignee && <p>Zuständig: {item.workflow.assignee}</p>}
          {item.workflow.waiting_for && <p>Wartet auf: {item.workflow.waiting_for}</p>}
          {!!item.workflow.blockers.length && <details><summary>Offene Voraussetzungen ({item.workflow.blockers.length})</summary><ul>{item.workflow.blockers.map((text, index) => <li key={index}>{text}</li>)}</ul></details>}
          {item.workflow.steps && <ol className="work-flow-steps">{item.workflow.steps.map(step => <li key={step.id}><Link to={step.href}>{step.label}</Link> · {step.done ? 'nachgewiesen' : 'offen'}</li>)}</ol>}
          <p className="work-item-context">Fristgrundlage: {item.workflow.deadline_basis}</p>
          {item.workflow.escalation.status === 'overdue' && <p>Bearbeitungsfrist seit {item.workflow.escalation.days_overdue} Tagen überschritten.</p>}
        </div>}
        {item.kind === 'task' && item.assignee && <p className="work-item-context">Zuständig: {item.assignee}</p>}
        <p className="work-item-context">{item.due_date ? `Fällig: ${formatDate(item.due_date)}` : 'Ohne Fälligkeitsdatum'}{item.deferred_until && ` · Persönlich zurückgestellt bis ${formatDate(item.deferred_until)}`}</p>
        <div className="work-item-actions"><Link className="btn btn-sm btn-primary" to={item.href}>{item.workflow?.next_action?.allowed && item.workflow.next_action.href === item.href ? item.workflow.next_action.label : 'Vorgang öffnen'}</Link>
          {(item.actions || []).filter(action => action.allowed && action.href && action.href !== item.href).map(action => <Link className="btn btn-sm btn-secondary" key={action.id} to={action.href}>{action.label}</Link>)}
          {(item.actions || []).some(action => action.id === 'note' && action.allowed) && <button type="button" className="btn btn-sm btn-secondary"
            onClick={() => setConversation(item)}>Gespräch / Wiedervorlage</button>}
          {item.kind === 'task' && item.can_edit && auth?.user && mayWrite(auth.write, '/tasks') && <InlineFieldEditor
            record={{ id: item.entity_id, updated_at: item.revision, title: item.title, status: item.status }} field="status" label="Status" canEdit onSaved={changed}
            options={[{ value: 'open', label: 'Offen' }, { value: 'in_progress', label: 'In Arbeit' }, { value: 'completed', label: 'Erledigt' }, { value: 'cancelled', label: 'Abgebrochen' }]}><StatusBadge status={item.status} /></InlineFieldEditor>}
          {item.kind === 'task' && item.can_edit && auth?.user && mayWrite(auth.write, '/tasks') && <>
            <InlineFieldEditor record={{ id: item.entity_id, updated_at: item.revision, title: item.title, due_date: item.due_date }}
              field="due_date" type="date" label="Fälligkeit" canEdit onSaved={changed}>Fälligkeit ändern</InlineFieldEditor>
            <InlineFieldEditor record={{ id: item.entity_id, updated_at: item.revision, title: item.title, assignee: item.assignee }}
              field="assignee" label="Zuständigkeit" canEdit onSaved={changed}>Zuständigkeit ändern</InlineFieldEditor>
          </>}
          <DeferralControl item={item} onChanged={refresh} />
        </div>
      </li>)}</ul>
      <FeedState feed={feed} empty="Keine offenen Vorgänge für diese Filter." />
    </section>
    {conversation && <ConversationDialog key={conversation.work_item_key} entityType={conversation.entity_type || conversation.kind}
      entityId={conversation.entity_id} entityRevision={conversation.revision} title={conversation.title}
      onClose={() => setConversation(null)} onSaved={() => { store?.invalidateRelated('tasks'); refresh(); }} />}
  </div>;
}
