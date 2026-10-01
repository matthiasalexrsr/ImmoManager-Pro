import { useTranslation } from '../i18n';

const COLORS = {
  active: 'badge-green', aktiv: 'badge-green', open: 'badge-blue', offen: 'badge-blue',
  draft: 'badge-gray', entwurf: 'badge-gray', vacant: 'badge-yellow', leer: 'badge-yellow',
  occupied: 'badge-green', belegt: 'badge-green', terminated: 'badge-red', gekündigt: 'badge-red',
  expired: 'badge-red', completed: 'badge-green', erledigt: 'badge-green',
  in_progress: 'badge-blue', held: 'badge-yellow', returned: 'badge-green',
  overdue: 'badge-red', warning: 'badge-yellow', info: 'badge-blue',
  paid: 'badge-green', partial: 'badge-yellow', cancelled: 'badge-gray',
  unread: 'badge-blue', read: 'badge-gray', new: 'badge-green', scheduled: 'badge-blue',
};

export default function StatusBadge({ status }) {
  const { t } = useTranslation();
  if (!status) return null;
  const cls = COLORS[status.toLowerCase()] || 'badge-gray';
  const key = `status.payment.${status.toLowerCase()}`;
  const label = t(key);
  return <span className={`badge ${cls}`}>{label === key ? status : label}</span>;
}
