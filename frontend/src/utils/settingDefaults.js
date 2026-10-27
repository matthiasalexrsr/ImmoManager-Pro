// Prefill a new manual claim only. Days 29?31 use the last available day.
export function defaultDueDate(day, today = new Date()) {
  const requested = Math.max(1, Math.min(31, Number(day) || 1));
  const candidate = month => new Date(today.getFullYear(), month,
    Math.min(requested, new Date(today.getFullYear(), month + 1, 0).getDate()));
  let due = candidate(today.getMonth());
  if (due < new Date(today.getFullYear(), today.getMonth(), today.getDate())) due = candidate(today.getMonth() + 1);
  return `${due.getFullYear()}-${String(due.getMonth() + 1).padStart(2, '0')}-${String(due.getDate()).padStart(2, '0')}`;
}
