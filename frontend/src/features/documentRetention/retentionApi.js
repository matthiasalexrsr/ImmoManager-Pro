import { api } from '../../api';

export const retentionService = {
  load: options => api.get('/documents/retention', options),
  remove: (id, reason) => api.del(`/documents/${encodeURIComponent(id)}${reason ? `?${new URLSearchParams({ retention_override: reason })}` : ''}`),
};

const day = value => value ? new Date(`${value}T00:00:00`).toLocaleDateString('de-DE') : '';

/** Short text for the list: "bis 31.12.2033", "abgelaufen", "dauerhaft" … */
export function retentionCell(item) {
  if (!item) return '—';
  if (item.state === 'none') return '—';
  if (item.state === 'permanent') return 'dauerhaft';
  if (item.state === 'open') return 'bis Vertragsende + ' + item.years + ' J.';
  if (item.state === 'ended') return `abgelaufen ${day(item.until)}`;
  return `bis ${day(item.until)}`;
}

/** Options of the form field: automatic by type, then every class with its years. */
export function retentionOptions(rules) {
  const years = item => item.years === null || item.years === undefined ? ''
    : item.key === 'contract' ? ` (${item.years} Jahre nach Vertragsende)` : ` (${item.years} Jahre)`;
  return [{ value: '', label: 'Automatisch nach Dokumenttyp' },
    ...(rules?.classes || []).map(item => ({ value: item.key, label: item.label + years(item) }))];
}
