// CSV quoting alone does not prevent spreadsheet programs from executing formulas.
// Actual numbers remain numeric; text stays text even when it resembles a formula.
export function csvCell(value, delimiter = ',') {
  if (value == null) return '';
  let text = String(value);
  let start = 0;
  while (start < text.length && (text.charCodeAt(start) <= 32 || text[start].trim() === '')) start += 1;
  if (typeof value !== 'number' && (/^[=+\-@]/u.test(text.slice(start)) || ['\t', '\r', '\n'].includes(text[0]))) {
    text = `'${text}`;
  }
  return text.includes(delimiter) || /["\r\n]/u.test(text) ? `"${text.replace(/"/gu, '""')}"` : text;
}
