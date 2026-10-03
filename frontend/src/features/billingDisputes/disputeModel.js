export const DISPUTES = '/billing/disputes';
export const PAGE_SIZE = 25;
export const states = ['open', 'in_review', 'withdrawn', 'closed'];
export const kinds = ['opened', 'note', 'in_review', 'withdrawn', 'closed', 'reopened', 'correction', 'correction_link'];
const immutable = new Set(['finalized', 'delivered', 'disputed', 'corrected']);
const identifier = value => typeof value === 'string' && value.length > 0;
const revision = value => Number.isSafeInteger(value) && value > 0;
const hash = value => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
const day = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value);
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const invalid = () => { throw new Error('invalidDisputeResponse'); };
export const denied = error => [401, 403, 404].includes(error?.statusCode);
export const copy = value => JSON.parse(JSON.stringify(value));
export const canonical = value => JSON.stringify(normalize(value));
function normalize(value) {
  if (Array.isArray(value)) return value.map(normalize);
  if (object(value)) return Object.fromEntries(Object.keys(value).sort().map(key => [key, normalize(value[key])]));
  return value;
}

export function readManifest(row) {
  if (!row || !identifier(row.document_id) || !identifier(row.version_id) || !hash(row.sha256)
    || !identifier(row.filename) || !Number.isSafeInteger(row.size_bytes) || row.size_bytes < 0
    || typeof row.media_type !== 'string') invalid();
  return row;
}

export function readEvent(row, caseId) {
  if (!row || !identifier(row.id) || row.case_id !== caseId || !revision(row.revision)
    || !kinds.includes(row.kind) || !identifier(row.reason) || !day(row.observed_on)
    || typeof row.created_at !== 'string' || !identifier(row.actor_id)
    || !Array.isArray(row.line_item_refs) || !row.line_item_refs.every(index => Number.isSafeInteger(index) && index >= 0)
    || !Array.isArray(row.evidence)) invalid();
  row.evidence.forEach(readManifest);
  return row;
}

export function readCase(row, caseId, periodId) {
  if (!row || row.id !== caseId || row.period_id !== periodId || !states.includes(row.state)
    || !revision(row.revision) || !hash(row.original_hash) || !hash(row.snapshot_hash)
    || !object(row.original_snapshot) || !['tenant_statement', 'property_review'].includes(row.case_kind)) invalid();
  if (row.case_kind === 'tenant_statement' && (!identifier(row.statement_id)
    || row.original_snapshot.id !== row.statement_id || row.original_snapshot.revision !== row.statement_revision)) invalid();
  if (row.case_kind === 'property_review' && (row.statement_id !== null || row.original_snapshot.period_id !== periodId)) invalid();
  if (readEvent(row.latest_event, caseId).revision !== row.revision) invalid();
  return row;
}

export function readCasePage(page, periodId) {
  if (!page || !Array.isArray(page.items) || page.items.length > PAGE_SIZE
    || !(page.next_after_id === null || identifier(page.next_after_id))
    || new Set(page.items.map(row => row?.id)).size !== page.items.length) invalid();
  if (page.items.some(row => !identifier(row?.id) || row.period_id !== periodId || !revision(row.revision)
    || !states.includes(row.state) || !['tenant_statement', 'property_review'].includes(row.case_kind))) invalid();
  if (page.next_after_id !== null && page.items.at(-1)?.id !== page.next_after_id) invalid();
  return page;
}

export function readJournal(page, caseId, after = 0) {
  if (!page || !Array.isArray(page.items) || page.items.length > PAGE_SIZE || !revision(page.revision)
    || !(page.next_after === null || revision(page.next_after))) invalid();
  let previous = after;
  for (const row of page.items) {
    readEvent(row, caseId);
    if (row.revision <= previous || row.revision > page.revision) invalid();
    previous = row.revision;
  }
  if (page.next_after !== null && page.items.at(-1)?.revision !== page.next_after) invalid();
  return page;
}

export function readStatus(row, periodId) {
  if (!row || row.period_id !== periodId || typeof row.legacy_disputed_without_complete_case !== 'boolean'
    || !Number.isSafeInteger(row.case_count) || row.case_count < 0
    || !Number.isSafeInteger(row.open_case_count) || row.open_case_count < 0 || row.open_case_count > row.case_count
    || !(row.property_review_original === null && row.property_review_snapshot_hash === null
      || object(row.property_review_original) && row.property_review_original.period_id === periodId && hash(row.property_review_snapshot_hash))) invalid();
  return row;
}

export function readStatement(row, statementId, periodId) {
  if (!row || row.id !== statementId || row.billing_period_id !== periodId || !immutable.has(row.status)
    || !revision(row.revision) || !hash(row.snapshot_hash) || !identifier(row.contract_id) || !identifier(row.unit_id)
    || !['total_cost', 'advance_paid', 'balance'].every(key => typeof row[key] === 'number' && Number.isFinite(row[key]))
    || !(row.line_items === null || Array.isArray(row.line_items))) invalid();
  return row;
}

export function permittedEvents(state, caseKind) {
  const common = ['note', 'correction', ...(caseKind === 'tenant_statement' ? ['correction_link'] : [])];
  return [...common, ...(state === 'open' || state === 'in_review' ? ['in_review', 'withdrawn', 'closed'] : ['reopened'])];
}

export function openCommand(periodId, source, caseKind = 'tenant_statement', key = crypto.randomUUID()) {
  return { idempotency_key: key, reason: '', evidence_version_ids: [], expected_case_revision: 0,
    case_kind: caseKind, period_id: periodId, statement_id: caseKind === 'tenant_statement' ? source.id : null,
    expected_statement_revision: caseKind === 'tenant_statement' ? source.revision : null,
    expected_snapshot_hash: caseKind === 'tenant_statement' ? source.snapshot_hash : source.property_review_snapshot_hash,
    received_on: '', line_item_refs: [] };
}

export function appendCommand(caseRow, kind, key = crypto.randomUUID()) {
  if (!permittedEvents(caseRow.state, caseRow.case_kind).includes(kind)) invalid();
  return { idempotency_key: key, reason: '', evidence_version_ids: [], expected_revision: caseRow.revision,
    kind, observed_on: '', corrects_event_id: null, correction_statement_id: null };
}

export function readPreview(result, command, caseId = null) {
  const { preview_hash: _oldHash, ...request } = command;
  if (!result || !hash(result.preview_hash) || !object(result.binding) || !Array.isArray(result.evidence)
    || canonical(result.request) !== canonical(request)) invalid();
  if (caseId ? result.binding.id !== caseId || result.binding.revision !== command.expected_revision
    : result.binding.period_id !== command.period_id || result.binding.statement_id !== command.statement_id
      || result.binding.snapshot_hash !== command.expected_snapshot_hash
      || result.binding.statement_revision !== command.expected_statement_revision) invalid();
  result.evidence.forEach(readManifest);
  if (new Set(result.evidence.map(row => row.version_id)).size !== result.evidence.length
    || canonical([...result.evidence.map(row => row.version_id)].sort()) !== canonical([...command.evidence_version_ids].sort())) invalid();
  return { review: copy(result), command: { ...copy(result.request), preview_hash: result.preview_hash } };
}

export function readReceipt(result, command, caseId = null) {
  if (!result || !identifier(result.case_id) || !identifier(result.event_id)
    || result.revision !== (caseId ? command.expected_revision : command.expected_case_revision) + 1
    || caseId && result.case_id !== caseId) invalid();
  return result;
}

export function restoreEnvelope(values, periodId, caseId = '') {
  if (values?.period_id !== periodId || (values.case_id || '') !== caseId
    || typeof values.command_json !== 'string' || typeof values.review_json !== 'string') invalid();
  const command = JSON.parse(values.command_json);
  const review = values.review_json ? JSON.parse(values.review_json) : null;
  if (!object(command) || !identifier(command.idempotency_key)
    || (caseId ? !revision(command.expected_revision) || !kinds.includes(command.kind)
      : command.period_id !== periodId || command.expected_case_revision !== 0)) invalid();
  if (review) readPreview(review, command, caseId || null);
  return { command, review };
}
