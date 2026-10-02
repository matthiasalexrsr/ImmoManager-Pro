const hash = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const count = value => Number.isSafeInteger(value) && value >= 0;

export function checkedBankImport(value, accountId) {
  if (!value || typeof value.id !== 'string' || !value.id || value.account_id !== accountId
    || !['ready', 'invalid', 'committed'].includes(value.state) || !count(value.revision)
    || !hash(value.source_sha256) || !hash(value.preview_hash) || !hash(value.mapping_hash)
    || !['csv', 'mt940'].includes(value.mapping?.format) || value.mapping.version !== 1
    || !['row_count', 'error_count', 'duplicate_count', 'published_count', 'source_bytes'].every(key => count(value[key]))
    || typeof value.filename !== 'string' || typeof value.persistent !== 'boolean'
    || !count(value.maximum_page_size) || value.maximum_page_size < 1) {
    throw new Error('bankImport.invalidResponse');
  }
  return value;
}

export function checkedBankPreview(value, job) {
  if (!value || value.import_id !== job.id || value.preview_hash !== job.preview_hash
    || !Array.isArray(value.items) || typeof value.has_more !== 'boolean'
    || (value.has_more ? typeof value.next_cursor !== 'string' || !value.next_cursor : value.next_cursor !== null)
    || !value.items.every(row => count(row.ordinal) && row.ordinal > 0 && count(row.source_line)
      && typeof row.payment_text === 'string' && (row.amount_cents === null || Number.isSafeInteger(row.amount_cents))
      && (row.error_code === null || typeof row.error_code === 'string')
      && (row.error_message === null || typeof row.error_message === 'string')
      && (row.duplicate_booking_id === null || typeof row.duplicate_booking_id === 'string'))) {
    throw new Error('bankImport.invalidResponse');
  }
  return value;
}
