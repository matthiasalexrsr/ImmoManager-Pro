import { useTranslation } from '../i18n';
import './SharedComponents.css';

const COLORS = {
  active: 'badge-green', aktiv: 'badge-green', open: 'badge-blue', offen: 'badge-blue',
  draft: 'badge-gray', entwurf: 'badge-gray', vacant: 'badge-yellow', leer: 'badge-yellow',
  occupied: 'badge-green', belegt: 'badge-green', terminated: 'badge-red', gekündigt: 'badge-red',
  expired: 'badge-red', completed: 'badge-green', erledigt: 'badge-green',
  in_progress: 'badge-blue', held: 'badge-yellow', returned: 'badge-green',
  overdue: 'badge-red', warning: 'badge-yellow', info: 'badge-blue',
  paid: 'badge-green', partial: 'badge-yellow', cancelled: 'badge-gray',
  unread: 'badge-blue', read: 'badge-gray', new: 'badge-green', scheduled: 'badge-blue',
  inactive: 'badge-gray', archived: 'badge-gray', pending: 'badge-yellow', locked: 'badge-gray',
  partiallypaid: 'badge-yellow', partially_paid: 'badge-yellow', ended: 'badge-gray',
  expiring: 'badge-yellow', inreview: 'badge-yellow', review: 'badge-yellow', void: 'badge-gray',
};

const LABELS = {
  active: 'status.general.active', aktiv: 'status.general.active', inactive: 'status.general.inactive',
  archived: 'status.general.archived', draft: 'status.general.draft', entwurf: 'status.general.draft',
  pending: 'status.general.pending', completed: 'status.general.completed', erledigt: 'status.general.completed',
  locked: 'status.general.locked', paid: 'status.payment.paid', partial: 'status.payment.partial',
  partiallypaid: 'status.payment.partiallyPaid', partially_paid: 'status.payment.partiallyPaid',
  open: 'status.payment.open', offen: 'status.payment.open', overdue: 'status.payment.overdue',
  cancelled: 'status.payment.cancelled', terminated: 'status.contract.terminated', gekündigt: 'status.contract.terminated',
  ended: 'status.contract.ended', expiring: 'status.contract.expiring', inreview: 'status.contract.inReview', review: 'status.contract.inReview',
};

export default function StatusBadge({ status }) {
  const { t } = useTranslation();
  if (status == null || !String(status).trim()) return null;
  const original = String(status).trim();
  const normalized = original.toLowerCase();
  const cls = COLORS[normalized] || 'badge-gray';
  const key = LABELS[normalized];
  const label = key ? t(key) : original;
  return <span className={`badge ${cls} shared-status-badge`}><span className="shared-status-dot" aria-hidden="true" /><span>{label === key ? original : label}</span></span>;
}
