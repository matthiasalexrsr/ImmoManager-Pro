// "Duplizieren": a new record prefilled from an existing one. What identifies or belongs only to
// the original (its id, state, number, receipt, links) is left out, so saving creates a new record.
const ALWAYS = ['id', 'created_at', 'updated_at'];

export function duplicateOf(row, omit = []) {
  const copy = { ...row };
  [...ALWAYS, ...omit].forEach(key => { delete copy[key]; });
  return copy;
}
