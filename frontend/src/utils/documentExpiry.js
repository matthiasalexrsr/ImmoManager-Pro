// The state of a document's expiry, as the daily reminder job sees it: reminded from
// `reminder_days` (30 if empty) before `valid_until` on.
const DAY = 86_400_000;

function localDay(value) {
  const [year, month, day] = String(value).slice(0, 10).split('-').map(Number);
  return Date.UTC(year, month - 1, day);
}

export function expiryState(document, today = new Date()) {
  if (!document?.valid_until) return null;
  const now = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  const days = Math.round((localDay(document.valid_until) - now) / DAY);
  if (days < 0) return 'expired';
  const lead = Number.isInteger(document.reminder_days) ? document.reminder_days : 30;
  return days <= lead ? 'due' : 'valid';
}
