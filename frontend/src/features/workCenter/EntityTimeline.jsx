import { Link } from 'react-router-dom';
import useCursorFeed from './useCursorFeed';
import FeedState from './FeedState';
import { formatDateTime } from '../../utils/format';
import { changeValue, fieldLabel, plainField } from '../../utils/changeDisplay';
import { useTranslation } from '../../i18n';
import './workCenter.css';
import './EntityTimeline.css';

const changeField = item => item.field_name || /^Änderung:\s*(.+)$/.exec(item.title || '')?.[1];
const eventTitle = item => {
  const field = changeField(item);
  return field ? `Änderung: ${fieldLabel(field)}` : item.title;
};

function ChangeValues({ item, t }) {
  const field = plainField(changeField(item));
  if (!field || (!Object.hasOwn(item, 'old_value') && !Object.hasOwn(item, 'new_value'))) return null;
  const display = value => changeValue(field, value, t);
  return <dl className="work-timeline-change" aria-label="Geänderte Werte">
    <div><dt>Vorher</dt><dd className="work-preserve-lines">{display(item.old_value)}</dd></div>
    <div><dt>Nachher</dt><dd className="work-preserve-lines">{display(item.new_value)}</dd></div>
  </dl>;
}

export default function EntityTimeline({ entityType, entityId, revision = 0 }) {
  return <Timeline key={`${entityType}:${entityId}:${revision}`} entityType={entityType} entityId={entityId} />;
}

function Timeline({ entityType, entityId }) {
  const { t } = useTranslation();
  const path = `/work-center/timeline?entity_type=${encodeURIComponent(entityType)}&entity_id=${encodeURIComponent(entityId)}&limit=25`;
  const feed = useCursorFeed(path, Boolean(entityType && entityId));
  return <section className="work-timeline" aria-label="Aktivitäten">
    <h3>Aktivitäten</h3><p className="text-muted">Notizen, Aufgaben, Dokumente und Änderungen zu diesem Vorgang.</p>
    <ol>{feed.items.map(item => <li key={item.id}>
      <div className="work-timeline-meta"><time dateTime={item.occurred_at}>{formatDateTime(item.occurred_at)}</time>{item.actor && <span>{typeof item.actor === 'object' ? item.actor.name || item.actor.username : item.actor}</span>}</div>
      <strong>{eventTitle(item)}</strong>
      <ChangeValues item={item} t={t} />
      {item.body && <p className="work-preserve-lines">{item.body}</p>}
      {item.entity?.href && <Link to={item.entity.href}>Vorgang öffnen</Link>}
    </li>)}</ol>
    <FeedState feed={feed} empty="Noch keine Aktivitäten vorhanden." />
  </section>;
}
