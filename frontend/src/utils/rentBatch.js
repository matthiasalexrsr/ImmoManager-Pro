const states = new Set(['preparing', 'ready', 'running', 'paused', 'done']);

export function checkedRentBatch(value) {
  if (!value || typeof value.id !== 'string' || !states.has(value.state) || typeof value.cursor !== 'string'
    || !Number.isInteger(value.revision) || !value.parameters || typeof value.persistent !== 'boolean'
    || !['contract_count', 'price_count', 'examined_count', 'created_count', 'existing_count'].every(key => Number.isInteger(value[key]) && value[key] >= 0)) {
    throw new Error('Invalid saved rental batch');
  }
  return value;
}
