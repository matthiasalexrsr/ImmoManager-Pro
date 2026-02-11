const COLORS = {
  active: 'badge-green', aktiv: 'badge-green', open: 'badge-blue', offen: 'badge-blue',
  draft: 'badge-gray', entwurf: 'badge-gray', vacant: 'badge-yellow', leer: 'badge-yellow',
  occupied: 'badge-green', belegt: 'badge-green', terminated: 'badge-red', gekündigt: 'badge-red',
  expired: 'badge-red', completed: 'badge-green', erledigt: 'badge-green',
  in_progress: 'badge-blue', held: 'badge-yellow', returned: 'badge-green',
  overdue: 'badge-red', warning: 'badge-yellow', info: 'badge-blue',
  unread: 'badge-blue', read: 'badge-gray', new: 'badge-green', scheduled: 'badge-blue',
};

export default function StatusBadge({ status }) {
  if (!status) return null;
  const cls = COLORS[status.toLowerCase()] || 'badge-gray';
  return <span className={`badge ${cls}`}>{status}</span>;
}
