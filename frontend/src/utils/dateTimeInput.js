/** Maintenance appointments use local wall time (also used by the date/time calendar fields). */
export function localDateTimeInput(value) {
  if (!value) return '';
  const instant = new Date(value);
  if (!Number.isFinite(instant.getTime())) return '';
  const local = new Date(instant.getTime() - instant.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 19);
}

export function saveLocalDateTime(value, original) {
  if (!value) return null;
  value = value.replace(/\.0+$/, '');
  // Preserve the exact original, including the repeated hour when DST ends.
  if (original && value === localDateTimeInput(original)) return original;
  const instant = new Date(value);
  if (!Number.isFinite(instant.getTime()) || localDateTimeInput(instant) !== (value.length === 16 ? `${value}:00` : value)) {
    throw new Error('Bitte ein gültiges Datum mit Uhrzeit wählen. Die Uhrzeit muss auch am Tag der Zeitumstellung existieren.');
  }
  // The existing appointment column has no time zone. Sending UTC here would
  // silently move the clock when SQL drops the suffix. Keep local wall time.
  return value.length === 16 ? `${value}:00` : value;
}
