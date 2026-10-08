import { useTranslation } from '../i18n';

const COLORS = {
  active: 'badge-green', aktiv: 'badge-green', open: 'badge-blue', offen: 'badge-blue',
  draft: 'badge-gray', entwurf: 'badge-gray', vacant: 'badge-yellow', leer: 'badge-yellow',
  occupied: 'badge-green', belegt: 'badge-green', terminated: 'badge-red', gekündigt: 'badge-red',
  expired: 'badge-red', completed: 'badge-green', erledigt: 'badge-green',
  in_progress: 'badge-blue', held: 'badge-yellow', returned: 'badge-green',
  overdue: 'badge-red', warning: 'badge-yellow', info: 'badge-blue',
  unread: 'badge-blue', read: 'badge-gray', new: 'badge-green', scheduled: 'badge-blue',
  finalized: 'badge-green', delivered: 'badge-green', paid: 'badge-green', review: 'badge-blue',
  reserved: 'badge-blue', partial: 'badge-yellow', pending: 'badge-yellow', disputed: 'badge-red',
  critical: 'badge-red', urgent: 'badge-red', high: 'badge-yellow', medium: 'badge-blue', normal: 'badge-blue',
  low: 'badge-gray', booked: 'badge-gray', cancelled: 'badge-gray', inactive: 'badge-gray', applied: 'badge-green',
  rejected: 'badge-red', archived: 'badge-gray', sent: 'badge-green', failed: 'badge-red',
};

export default function StatusBadge({ status }) {
  const { t } = useTranslation();
  if (!status) return null;
  const value = String(status);
  const key = value.toLowerCase();
  // Statuses are stored as English codes; show the translated word where there is one.
  const translated = t(`status.badge.${key}`);
  const label = translated === `status.badge.${key}` ? value : translated;
  return <span className={`badge ${COLORS[key] || 'badge-gray'}`}>{label}</span>;
}
