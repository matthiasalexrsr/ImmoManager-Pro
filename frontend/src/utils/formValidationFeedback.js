// Link only explicitly named, top-level server validation failures to visible form fields.
// Unrelated, nested, query, or malformed errors still appear in the form-level alert.
export function fieldValidationErrors(error, fields) {
  if (error?.statusCode !== 400 && error?.statusCode !== 422) return {};
  const visible = new Set(fields.filter(field => field.type !== 'hidden').map(field => field.key));
  const result = {};
  for (const item of Array.isArray(error.details) ? error.details : []) {
    if (!item || typeof item !== 'object') continue;
    let key;
    if (Array.isArray(item.loc) && item.loc.length === 2 && item.loc[0] === 'body'
      && typeof item.loc[1] === 'string') key = item.loc[1];
    else if (typeof item.field === 'string' && !item.field.includes('.')) key = item.field;
    if (!visible.has(key)) continue;
    const message = item.msg ?? item.message;
    if (typeof message !== 'string' || !message.trim()) continue;
    // shown under its field, whose label already names it ("actual_amount: Bitte …" → "Bitte …")
    (result[key] ??= []).push(message.replace(/^Value error, /, '').replace(new RegExp(`^${escaped(key)}: `), ''));
  }
  return result;
}

const escaped = text => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** A server message in the form's words: field keys become their labels ("actual_amount: …" → "Tatsächlicher Betrag (€): …"). */
export function labelledMessage(message, fields) {
  if (typeof message !== 'string') return message;
  let text = message;
  for (const field of fields || []) {
    if (!field?.key || typeof field.label !== 'string' || field.type === 'hidden') continue;
    text = text.replace(new RegExp(`(^|;\\s*|Pflichtangabe fehlt: )${escaped(field.key)}(?=:|;|$)`, 'g'), `$1${field.label}`);
  }
  return text;
}
