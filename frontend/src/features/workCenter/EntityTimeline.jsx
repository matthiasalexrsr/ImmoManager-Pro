import { Link } from 'react-router-dom';
import useCursorFeed from './useCursorFeed';
import FeedState from './FeedState';
import { formatDate, formatDateTime } from '../../utils/format';
import { codeLabel } from '../../utils/codeLabels';
import { useTranslation } from '../../i18n';
import './workCenter.css';
import './EntityTimeline.css';

const FIELD_LABELS = {
  title: 'Titel', name: 'Name', full_name: 'Name', label: 'Bezeichnung', status: 'Status', priority: 'Priorität',
  description: 'Beschreibung', notes: 'Notizen', body: 'Notiz', reason: 'Grund', assignee: 'Zuständigkeit',
  email: 'E-Mail', phone: 'Telefon', address: 'Anschrift', address_line: 'Straße', street: 'Straße',
  city: 'Ort', postal_code: 'Postleitzahl', country: 'Land',
  type: 'Art', property_type: 'Immobilienart', document_type: 'Dokumentart', payment_method: 'Zahlungsart',
  frequency: 'Intervall', role: 'Rolle', due_date: 'Fälligkeit', start_date: 'Beginn', end_date: 'Ende',
  booking_date: 'Buchungsdatum', invoice_date: 'Rechnungsdatum', received_on: 'Eingangsdatum', protocol_date: 'Protokolldatum',
  next_inspection: 'Nächste Prüfung', actual_move_in_date: 'Tatsächlicher Einzug', amount: 'Betrag', total_amount: 'Gesamtbetrag',
  cold_rent: 'Kaltmiete', deposit: 'Kaution', area: 'Fläche', archived: 'Archiviert', active: 'Aktiv',
  recoverable: 'Umlagefähig', is_recoverable: 'Umlagefähig', sepa_mandate: 'SEPA-Mandat',
  severity: 'Schweregrad', location: 'Ort', condition: 'Zustand', remedy: 'Maßnahme',
  property_id: 'Immobilienkennung', unit_id: 'Einheitenkennung', tenant_id: 'Parteikennung', contract_id: 'Vertragskennung',
  document_id: 'Dokumentkennung', account_id: 'Kontokennung', category_id: 'Kategorienkennung',
};
const DATE_FIELDS = new Set(['due_date', 'start_date', 'end_date', 'booking_date', 'invoice_date', 'received_on', 'protocol_date', 'next_inspection', 'actual_move_in_date']);
const BOOLEAN_FIELDS = new Set(['archived', 'active', 'recoverable', 'is_recoverable']);
const CODE_FIELDS = new Set(['status', 'priority', 'type', 'property_type', 'document_type', 'payment_method', 'frequency', 'role', 'condition']);
const plainField = field => field?.startsWith('defect:') ? field.split(':').slice(2).join(':') : field;
const fieldLabel = field => {
  const key = plainField(field);
  const label = FIELD_LABELS[key] || (key?.endsWith('_id') ? `${key.slice(0, -3)} (Kennung)` : key);
  return field?.startsWith('defect:') ? `Mangel (Kennung ${field.split(':')[1]}) – ${label}` : label;
};
const changeField = item => item.field_name || /^Änderung:\s*(.+)$/.exec(item.title || '')?.[1];
const eventTitle = item => {
  const field = changeField(item);
  return field ? `Änderung: ${fieldLabel(field)}` : item.title;
};

function ChangeValues({ item, t }) {
  const field = plainField(changeField(item));
  if (!field || (!Object.hasOwn(item, 'old_value') && !Object.hasOwn(item, 'new_value'))) return null;
  const display = value => {
    if (value == null || (typeof value === 'string' && !value.trim())) return 'Nicht angegeben';
    if (typeof value === 'boolean') return value ? 'Ja' : 'Nein';
    if (BOOLEAN_FIELDS.has(field) && /^(true|false)$/i.test(String(value))) return String(value).toLowerCase() === 'true' ? 'Ja' : 'Nein';
    if (DATE_FIELDS.has(field) && typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)) return formatDate(value);
    if (CODE_FIELDS.has(field) && typeof value === 'string') {
      const translation = t(`status.badge.${value}`);
      return translation && translation !== `status.badge.${value}` ? translation : codeLabel(value);
    }
    return typeof value === 'object' ? JSON.stringify(value) : String(value);
  };
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
