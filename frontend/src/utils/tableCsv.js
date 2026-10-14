// CSV for the table export, in the form the server's own exports use: semicolon separated,
// UTF-8 with BOM, CRLF lines. German spreadsheet programs open it in columns directly.
const NUMERIC = new Set(['number', 'currency']);
const NUMBER_TEXT = /^-?\d+(\.\d+)?$/;

function quote(text) {
  return /[;"\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function csvCell(col, value) {
  if (value == null) return '';
  const text = String(value);
  // numbers keep their sign and get a decimal comma, so "12.50" is not read as a date or text
  if (NUMERIC.has(col.type) && NUMBER_TEXT.test(text.trim())) return text.trim().replace('.', ',');
  // a cell starting like a formula is written as text (spreadsheet formula injection)
  return quote(/^[=+\-@\t\r]/.test(text) ? `'${text}` : text);
}

export function buildCsv(columns, rows) {
  const header = columns.map(col => quote(String(col.label ?? col.key)));
  const lines = rows.map(row => columns.map(col => csvCell(col, row[col.key])).join(';'));
  return [header.join(';'), ...lines].join('\r\n');
}
