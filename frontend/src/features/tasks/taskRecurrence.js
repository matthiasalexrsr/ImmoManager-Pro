export const RECURRENCE_PRESETS = {
  daily: ['DAILY', '1'], weekly: ['WEEKLY', '1'], monthly: ['MONTHLY', '1'],
  quarterly: ['MONTHLY', '3'], halfYearly: ['MONTHLY', '6'], yearly: ['YEARLY', '1'],
};
export const RECURRENCE_FREQUENCIES = ['DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY'];
const positiveInteger = value => /^[0-9]+$/.test(value) && /[1-9]/.test(value);
const calendarDate = value => {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split('-').map(Number);
  if (year < 1 || month < 1 || month > 12 || day < 1) return false;
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  return day <= [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1];
};

function ruleParts(rule) {
  const parts = {};
  for (const token of rule.split(';')) {
    const equal = token.indexOf('=');
    if (equal < 0) return null;
    const key = token.slice(0, equal).trim().toUpperCase();
    if (!['FREQ', 'INTERVAL', 'COUNT', 'UNTIL'].includes(key) || Object.hasOwn(parts, key)) return null;
    parts[key] = token.slice(equal + 1).trim().toUpperCase();
  }
  if (!RECURRENCE_FREQUENCIES.includes(parts.FREQ)) return null;
  return parts;
}

// Python date.fromisoformat also accepts compact dates and ISO week dates.
// Those retained rules stay in the expert editor without rewriting their text.
function validUntil(value) {
  if (calendarDate(value)) return true;
  if (/^\d{8}$/.test(value)) return calendarDate(`${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`);
  const week = /^(\d{4})-W(\d{2})(?:-([1-7]))?$/.exec(value) || /^(\d{4})W(\d{2})([1-7])?$/.exec(value);
  if (!week || Number(week[1]) < 1 || Number(week[2]) < 1 || Number(week[2]) > 53) return false;
  const first = new Date(0);
  first.setUTCFullYear(Number(week[1]), 0, 4);
  const mondayOffset = (first.getUTCDay() + 6) % 7;
  first.setUTCDate(first.getUTCDate() - mondayOffset + (Number(week[2]) - 1) * 7 + 3);
  if (first.getUTCFullYear() !== Number(week[1])) return false;
  first.setUTCDate(first.getUTCDate() + Number(week[3] || 1) - 4);
  return first.getUTCFullYear() >= 1 && first.getUTCFullYear() <= 9999;
}

// Decode only: opening a field must never canonicalize a retained rule. Empty
// control values remain representable so unfinished edits also survive drafts.
export function recurrenceConfig(rule) {
  if (!rule) return { frequency: 'WEEKLY', interval: '1', end: 'never', count: '', until: '' };
  const parts = ruleParts(rule);
  if (!parts) return null;
  if (parts.UNTIL && !calendarDate(parts.UNTIL)) return null;
  if (['INTERVAL', 'COUNT'].some(key => parts[key] && !Number.isFinite(Number(parts[key])))) return null;
  const count = Object.hasOwn(parts, 'COUNT');
  const until = Object.hasOwn(parts, 'UNTIL');
  return { frequency: parts.FREQ, interval: parts.INTERVAL ?? '1',
    end: count && until ? 'both' : count ? 'count' : until ? 'until' : 'never',
    count: parts.COUNT ?? '', until: parts.UNTIL ?? '' };
}

export function recurrencePreset(rule) {
  if (!rule) return 'none';
  const config = recurrenceConfig(rule);
  if (!config || config.end !== 'never') return 'custom';
  return Object.entries(RECURRENCE_PRESETS).find(([, [freq, interval]]) =>
    config.frequency === freq && config.interval === interval)?.[0] || 'custom';
}

export function recurrenceRule(config) {
  let rule = `FREQ=${config.frequency};INTERVAL=${config.interval}`;
  if (['count', 'both'].includes(config.end)) rule += `;COUNT=${config.count}`;
  if (['until', 'both'].includes(config.end)) rule += `;UNTIL=${config.until}`;
  return rule;
}

export function recurrenceError(rule) {
  if (!rule) return null;
  const parts = ruleParts(rule);
  if (!parts) return 'invalidRule';
  if (!positiveInteger(parts.INTERVAL ?? '1')) return 'invalidInterval';
  if (Object.hasOwn(parts, 'COUNT') && !positiveInteger(parts.COUNT)) return 'invalidCount';
  if (Object.hasOwn(parts, 'UNTIL') && !validUntil(parts.UNTIL)) return 'invalidUntil';
  return null;
}

export function recurrenceSummary(rule, translate) {
  const t = translate;
  const preset = recurrencePreset(rule);
  if (preset !== 'custom') return t(`pages.tasks.recurrence.${preset}`);
  const config = recurrenceConfig(rule);
  if (!config || recurrenceError(rule)) return t('pages.tasks.recurrence.custom');
  let label = t('pages.tasks.recurrence.everySummary', { interval: config.interval, unit: t(`pages.tasks.recurrence.units.${config.frequency}`) });
  if (['count', 'both'].includes(config.end)) label += ` · ${t('pages.tasks.recurrence.countSummary', { count: config.count })}`;
  if (['until', 'both'].includes(config.end)) label += ` · ${t('pages.tasks.recurrence.untilSummary', { date: config.until })}`;
  return label;
}
