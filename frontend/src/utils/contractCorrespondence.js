import { snapshotRevision } from '../editRevision';

export const PAGE_SIZE = 25;
export const policy = 'manual_observation_only';
const object = value => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
const text = value => typeof value === 'string' && value.length > 0;
const date = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value);
const hash = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const etag = value => typeof value === 'string' && /^"[^"]+"$/.test(value);
const optionalId = value => value === null || text(value);
const fail = () => { throw new Error('invalidResponse'); };
const fields = ['letter_date', 'deadline_date', 'deadline_basis', 'deadline_confirmed', 'recipient_name',
  'recipient_address', 'subject', 'body', 'template_id', 'lifecycle_command_id'];

export function sourceContract(value, contractId) {
  if (!object(value) || value.id !== contractId || !['property_id', 'unit_id', 'tenant_id', 'contract_number'].every(key => text(value[key]))) fail();
  const tag = snapshotRevision(value)?.etag;
  if (!etag(tag)) fail();
  return { value, etag: tag };
}

export function validateLetterData(data) {
  if (!object(data) || !date(data.letter_date) || !date(data.deadline_date) || data.deadline_confirmed !== true
      || !['deadline_basis', 'recipient_name', 'recipient_address', 'subject'].every(key => text(data[key]) && data[key].trim())
      || !optionalId(data.template_id) || !optionalId(data.lifecycle_command_id)
      || (data.body === null ? !text(data.template_id) : !text(data.body) || data.template_id !== null)) fail();
  return data;
}

export function sameData(a, b) { return fields.every(key => (a?.[key] ?? null) === (b?.[key] ?? null)); }

export function validateLetter(row, source, actorId, { live = false, history = false } = {}) {
  if (!object(row) || !['id', 'portfolio_id', 'actor_id', 'revision', 'created_at'].every(key => text(row[key]))
      || row.contract_id !== source.id || ['property_id', 'unit_id', 'tenant_id'].some(key => row[key] !== source[key])
      || source.portfolio_id && row.portfolio_id !== source.portfolio_id
      || !['draft', 'reviewed', 'approved'].includes(row.state)
      || (row.actor_id !== actorId && (!history || row.state !== 'approved'))
      || typeof row.persistent !== 'boolean' || row.delivery_policy !== policy || !etag(row.source_contract_etag)
      || !optionalId(row.document_id) || !optionalId(row.document_version_id)) fail();
  validateLetterData(row.data);
  if (live && (!etag(row.current_contract_etag) || !['not_reviewed', 'current', 'requires_review'].includes(row.source_review_status))) fail();
  if (live && row.source_review_status === 'current' && row.current_contract_etag !== row.source_contract_etag) fail();
  if (row.state === 'draft') {
    if (row.review !== null || row.review_hash !== null || row.approved_at !== null || row.document_id !== null || row.document_version_id !== null) fail();
  } else {
    const review = row.review;
    if (!object(review) || !hash(row.review_hash) || !object(review.source_contract)
        || ['id', 'property_id', 'unit_id', 'tenant_id'].some(key => review.source_contract[key] !== source[key])
        || review.source_contract_etag !== row.source_contract_etag || !sameData(review.data, row.data)
        || !object(review.source_context) || review.source_context.portfolio_id !== row.portfolio_id
        || !['property_etag', 'unit_etag', 'tenant_etag'].every(key => etag(review.source_context[key]))
        || !object(review.source_context.names) || typeof review.rendered_body !== 'string' || !hash(review.pdf_sha256)) fail();
    if (review.template === null ? row.data.template_id !== null
      : !object(review.template) || review.template.id !== row.data.template_id || !text(review.template.root_id)
        || !Number.isSafeInteger(review.template.version) || review.template.version < 1
        || !text(review.template.title) || !hash(review.template.body_sha256)) fail();
    if (review.lifecycle === null ? row.data.lifecycle_command_id !== null
      : !object(review.lifecycle) || review.lifecycle.command_id !== row.data.lifecycle_command_id
        || !text(review.lifecycle.draft_id) || !hash(review.lifecycle.review_hash) || !hash(review.lifecycle.result_hash)
        || !['confirmed', 'pending_effective', 'completed'].includes(review.lifecycle.current_state)) fail();
    if (row.state === 'approved' ? !text(row.approved_at) || !text(row.document_id) || !text(row.document_version_id)
      : row.approved_at !== null || row.document_id !== null || row.document_version_id !== null) fail();
  }
  return row;
}

export function validateLetterPage(page, source, actorId, history = false) {
  if (!object(page) || !Array.isArray(page.items) || page.items.length > PAGE_SIZE
      || typeof page.has_more !== 'boolean' || typeof page.persistent !== 'boolean'
      || (page.has_more ? !text(page.next_before) || !page.items.length : page.next_before !== null)) fail();
  page.items.forEach(row => validateLetter(row, source, actorId, { live: true, history }));
  if (new Set(page.items.map(row => row.id)).size !== page.items.length || history && page.items.some(row => row.state !== 'approved')) fail();
  return page;
}

export function validateEvent(event) {
  const data = event?.data;
  if (!object(event) || !text(event.id) || !text(event.actor_id) || !text(event.created_at)
      || !Number.isSafeInteger(event.event_revision) || event.event_revision < 1 || event.policy !== policy
      || !object(data) || !['dispatched', 'received'].includes(data.kind) || !date(data.event_date)
      || !['post', 'handover', 'other'].includes(data.channel) || !text(data.reference) || !text(data.note)
      || data.confirmed !== true || !optionalId(data.dispatch_event_id)
      || (data.kind === 'received') !== (data.dispatch_event_id !== null)) fail();
  return event;
}

export function validateDeadlines(page, contractId) {
  if (!object(page) || !Array.isArray(page.items) || page.items.length > PAGE_SIZE
      || typeof page.has_more !== 'boolean' || typeof page.persistent !== 'boolean'
      || (page.has_more ? !text(page.next_before) || !page.items.length : page.next_before !== null)
      || !page.items.every(row => object(row) && row.contract_id === contractId && text(row.id)
        && date(row.date) && text(row.basis) && hash(row.review_hash)
        && row.policy === 'user_confirmed_management_date'
        && ['current', 'requires_review'].includes(row.source_review_status))
      || new Set(page.items.map(row => row.id)).size !== page.items.length) fail();
  return page;
}

export function validateEvents(page, versionId) {
  if (!object(page) || page.policy !== policy || page.document_version_id !== versionId || !Array.isArray(page.items)
      || page.items.length > PAGE_SIZE || !Number.isSafeInteger(page.event_revision) || page.event_revision < 0
      || !(page.next_before === null || Number.isSafeInteger(page.next_before) && page.next_before > 0)) fail();
  page.items.forEach(validateEvent);
  if (new Set(page.items.map(event => event.id)).size !== page.items.length
      || page.items.some(event => event.event_revision > page.event_revision)) fail();
  return page;
}

export function validateCommand(value, source, actorId, command) {
  const row = validateLetter(value, source, actorId, { history: command.operation === 'event' });
  const state = { create: 'draft', edit: 'draft', review: 'reviewed', approve: 'approved', event: 'approved' }[command.operation];
  if (row.state !== state || command.id && row.id !== command.id || !sameData(row.data, command.data)
      || command.reviewHash && row.review_hash !== command.reviewHash
      || command.operation !== 'event' && row.source_contract_etag !== command.payload.expected_contract_etag) fail();
  if (command.operation === 'event') {
    const event = validateEvent(row.event);
    if (event.actor_id !== actorId || event.event_revision !== command.payload.expected_event_revision + 1
        || ['kind', 'event_date', 'channel', 'reference', 'note', 'dispatch_event_id'].some(key =>
          (event.data[key] ?? null) !== (command.payload[key] ?? null))) fail();
  }
  return row;
}

export function blankLetter() {
  return { letter_date: '', deadline_date: '', deadline_basis: '', deadline_confirmed: false,
    recipient_name: '', recipient_address: '', subject: '', body: '', template_id: '', lifecycle_command_id: '', mode: 'body' };
}
export function letterForm(data) { return { ...blankLetter(), ...data, body: data.body || '',
  template_id: data.template_id || '', lifecycle_command_id: data.lifecycle_command_id || '', mode: data.template_id ? 'template' : 'body' }; }
export function letterData(form) {
  const data = Object.fromEntries(fields.map(key => [key, form[key]]));
  data.body = form.mode === 'body' ? form.body : null;
  data.template_id = form.mode === 'template' ? form.template_id || null : null;
  data.lifecycle_command_id ||= null;
  ['recipient_name', 'recipient_address', 'subject', 'deadline_basis'].forEach(key => { data[key] = data[key].trim(); });
  try { validateLetterData(data); } catch { throw new Error('completeFields'); }
  return data;
}
export const key = () => `g06-letter:${crypto.randomUUID()}`;
export const unknownOutcome = error => error.isNetwork || error.statusCode >= 500 || !error.statusCode && error.name !== 'AbortError';
