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
    (result[key] ??= []).push(message.replace(/^Value error, /, ''));
  }
  return result;
}
