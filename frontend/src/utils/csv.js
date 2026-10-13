// CSV quoting alone does not prevent spreadsheet programs from executing formulas.
// Actual numbers remain numeric; text stays text even when it resembles a formula.
export function csvCell(value) {
  if (value == null) return '';
  let text = String(value);
  if (typeof value !== 'number' && (/^[=+\-@]/u.test(text.trimStart()) || ['\t', '\r', '\n'].includes(text[0]))) {
    text = `'${text}`;
  }
  return /[,"\r\n]/u.test(text) ? `"${text.replace(/"/gu, '""')}"` : text;
}
