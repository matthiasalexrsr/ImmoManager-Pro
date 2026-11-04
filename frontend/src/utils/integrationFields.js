/** Preserve the provider's declared types across editable HTML field values. */
export const isIntegrationFieldEmpty = value => value === undefined || value === null || value === '';

export const isDefiniteIntegrationFailure = error => [400, 401, 403, 404, 409, 413, 422].includes(error?.statusCode);

export function initializeIntegrationValues(fields = [], values = {}) {
  return Object.fromEntries(fields.flatMap(field => {
    let value = values[field.key];
    if (field.secret && (value === '***' || isIntegrationFieldEmpty(value))) return [];
    if (value === undefined && !field.secret) value = field.default ?? (field.type === 'boolean' ? false : undefined);
    if (value === undefined) return [];
    if (['array', 'object'].includes(field.type) && typeof value !== 'string' && value !== null) {
      value = JSON.stringify(value, null, 2);
    }
    return [[field.key, value]];
  }));
}

export function serializeIntegrationValues(fields = [], values = {}, { retainedSecrets = [], emptyValue } = {}) {
  const result = {};
  for (const field of fields) {
    let value = values[field.key];
    const label = field.label || field.key;
    const invalid = message => { throw new Error(`${label}: ${message}`); };
    const empty = isIntegrationFieldEmpty(value) || (typeof value === 'string' && !value.trim());
    if (empty || (field.secret && value === '***')) {
      if (field.required && !(field.secret && retainedSecrets.includes(field.key))) invalid('Bitte ausfüllen.');
      if (!field.secret && Object.hasOwn(values, field.key) && value !== undefined && emptyValue !== undefined) result[field.key] = emptyValue;
      continue;
    }
    if (field.options) {
      const options = field.options.map(option => option?.value ?? option);
      const match = options.find(option => Object.is(option, value) || String(option) === String(value));
      if (match === undefined) invalid('Bitte einen unterstützten Wert wählen.');
      value = match;
    }
    if (field.type === 'array' || field.type === 'object') {
      if (typeof value === 'string') {
        try { value = JSON.parse(value); } catch { invalid('Bitte gültiges JSON eingeben.'); }
      }
      if (field.type === 'array' ? !Array.isArray(value) : value === null || typeof value !== 'object' || Array.isArray(value)) {
        invalid(field.type === 'array' ? 'Eine JSON-Liste wird benötigt.' : 'Ein JSON-Objekt wird benötigt.');
      }
    } else if (field.type === 'integer' || field.type === 'number') {
      if (typeof value === 'string') value = Number(value);
      if (typeof value !== 'number' || !Number.isFinite(value) || (field.type === 'integer' && !Number.isSafeInteger(value))) {
        invalid(field.type === 'integer' ? 'Bitte eine ganze Zahl eingeben.' : 'Bitte eine gültige Zahl eingeben.');
      }
      if ((field.min !== undefined && value < field.min) || (field.max !== undefined && value > field.max)) {
        invalid('Der Wert liegt außerhalb des erlaubten Bereichs.');
      }
    } else if (field.type === 'boolean') {
      if (typeof value !== 'boolean') invalid('Bitte einen Wahrheitswert wählen.');
    }
    result[field.key] = value;
  }
  return result;
}
