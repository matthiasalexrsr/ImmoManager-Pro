export const PAGE_SIZE = 25;

export const DIRECTIONS = Object.freeze(['move_in', 'move_out']);
export const CHANGE_MODES = Object.freeze(['move_in', 'move_out', 'turnover']);
export const REQUIREMENTS = Object.freeze(['required', 'optional']);
export const ANCHORS = Object.freeze([
  'previous_contract_end',
  'next_contract_start',
  'move_out_handover',
  'move_in_handover',
]);
export const EVIDENCE_REQUIREMENTS = Object.freeze([
  'none',
  'document_original',
  'handover_protocol',
  'meter_reading',
]);
export const STEP_STATES = Object.freeze([
  'open',
  'blocked',
  'in_progress',
  'completed',
  'not_applicable',
]);

const isObject = value => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
const isString = value => typeof value === 'string' && value.length > 0;
const optionalString = value => value == null || isString(value);
const optionalDate = value => value == null || /^\d{4}-\d{2}-\d{2}$/.test(value);
const isTimestamp = value => isString(value) && Number.isFinite(Date.parse(value));
const isStrongEtag = value => isString(value) && /^"[^"]+"$/.test(value) && !value.startsWith('W/');
const isSha256 = value => isString(value) && /^[a-f0-9]{64}$/i.test(value);

export function actionAllowed(record, name) {
  const actions = record?.actions;
  if (Array.isArray(actions)) return actions.includes(name);
  return isObject(actions) && actions[name] === true;
}

export function validateActions(actions) {
  if (Array.isArray(actions)) {
    if (!actions.every(isString) || new Set(actions).size !== actions.length) throw new Error('invalid_actions');
    return actions;
  }
  if (!isObject(actions) || !Object.values(actions).every(value => typeof value === 'boolean')) {
    throw new Error('invalid_actions');
  }
  return actions;
}

export function validateEvidenceLink(link) {
  if (!isObject(link) || !isString(link.id)
      || !['document_version', 'handover_protocol', 'meter_reading'].includes(link.kind)
      || !isSha256(link.snapshot_sha256) || !isTimestamp(link.created_at)) {
    throw new Error('invalid_evidence_link');
  }
  if (link.kind === 'document_version'
      && (!isString(link.document_id) || !isString(link.document_version_id)
        || link.handover_protocol_id != null || link.meter_reading_id != null)) {
    throw new Error('invalid_document_evidence');
  }
  if (link.kind === 'handover_protocol'
      && (!isString(link.handover_protocol_id) || link.document_id != null
        || link.document_version_id != null || link.meter_reading_id != null)) {
    throw new Error('invalid_handover_evidence');
  }
  if (link.kind === 'meter_reading'
      && (!isString(link.meter_reading_id) || link.document_id != null
        || link.document_version_id != null || link.handover_protocol_id != null)) {
    throw new Error('invalid_meter_evidence');
  }
  return link;
}

export function validateTemplateStep(step) {
  if (!isObject(step) || !isString(step.id) || !isString(step.stable_key)
      || !Number.isInteger(step.position) || step.position < 0
      || !isString(step.title) || !optionalString(step.description)
      || !REQUIREMENTS.includes(step.default_requirement)
      || !ANCHORS.includes(step.anchor) || !Number.isInteger(step.offset_days)
      || !optionalString(step.assignee_user_id) || !optionalString(step.assignee_role)
      || Boolean(step.assignee_user_id) === Boolean(step.assignee_role)
      || !Array.isArray(step.depends_on_step_keys)
      || !step.depends_on_step_keys.every(isString)
      || !EVIDENCE_REQUIREMENTS.includes(step.evidence_requirement)) {
    throw new Error('invalid_template_step');
  }
  return step;
}

export function validateTemplateDraftSteps(steps) {
  if (!Array.isArray(steps) || steps.length === 0) throw new Error('invalid_template_steps');
  const keys = new Set();
  const positions = new Set();
  for (const step of steps) {
    if (!isObject(step) || !isString(step.stable_key)
        || !/^[A-Za-z0-9_.:-]+$/.test(step.stable_key) || step.stable_key.length > 100
        || !isString(step.title) || step.title.length > 500
        || !(step.description == null || (typeof step.description === 'string' && step.description.length <= 5000))
        || !REQUIREMENTS.includes(step.default_requirement)
        || !ANCHORS.includes(step.anchor) || !Number.isInteger(Number(step.offset_days))
        || !Number.isInteger(Number(step.position)) || Number(step.position) < 0
        || Boolean(step.assignee_user_id) === Boolean(step.assignee_role)
        || !Array.isArray(step.depends_on_step_keys)
        || step.depends_on_step_keys.length !== new Set(step.depends_on_step_keys).size
        || !EVIDENCE_REQUIREMENTS.includes(step.evidence_requirement)) {
      throw new Error('invalid_template_step');
    }
    if (keys.has(step.stable_key)) throw new Error('duplicate_step_key');
    if (positions.has(Number(step.position))) throw new Error('duplicate_step_position');
    keys.add(step.stable_key);
    positions.add(Number(step.position));
  }
  for (const step of steps) {
    if (step.depends_on_step_keys.some(key => !keys.has(key) || key === step.stable_key)) {
      throw new Error('invalid_dependency');
    }
  }
  const visiting = new Set();
  const visited = new Set();
  const byKey = new Map(steps.map(step => [step.stable_key, step]));
  const visit = key => {
    if (visiting.has(key)) throw new Error('dependency_cycle');
    if (visited.has(key)) return;
    visiting.add(key);
    for (const dependency of byKey.get(key)?.depends_on_step_keys || []) visit(dependency);
    visiting.delete(key);
    visited.add(key);
  };
  for (const key of keys) visit(key);
  return steps;
}

export function validateTemplateVersion(value) {
  if (!isObject(value) || !isString(value.id) || !isString(value.template_id)
      || !isString(value.portfolio_id) || !isString(value.property_id)
      || !optionalString(value.unit_id) || !DIRECTIONS.includes(value.direction)
      || !Number.isInteger(value.version) || value.version < 1
      || !['draft', 'published', 'retired'].includes(value.state)
      || !optionalString(value.based_on_version_id)
      || !isString(value.revision) || !isStrongEtag(value.etag)
      || !isTimestamp(value.created_at)
      || !(value.published_at == null || isTimestamp(value.published_at))
      || !Array.isArray(value.steps)) {
    throw new Error('invalid_template_version');
  }
  value.steps.forEach(validateTemplateStep);
  validateTemplateDraftSteps(value.steps);
  validateActions(value.actions);
  return value;
}

export function validateStepInstance(step, changeId) {
  if (!isObject(step) || !isString(step.id) || step.tenancy_change_id !== changeId
      || !isString(step.template_step_key) || !DIRECTIONS.includes(step.direction)
      || !isString(step.title_snapshot) || !optionalString(step.description_snapshot)
      || !REQUIREMENTS.includes(step.requirement) || !optionalString(step.not_applicable_reason)
      || !ANCHORS.includes(step.anchor) || !Number.isInteger(step.offset_days)
      || !optionalDate(step.original_due_date) || !optionalDate(step.due_date)
      || !STEP_STATES.includes(step.state) || !Array.isArray(step.blocked_by_step_ids)
      || !step.blocked_by_step_ids.every(isString)
      || !optionalString(step.assignee_user_id) || !optionalString(step.assignee_role)
      || Boolean(step.assignee_user_id) === Boolean(step.assignee_role)
      || !optionalString(step.task_id)
      || !(step.completed_at == null || isTimestamp(step.completed_at))
      || !optionalString(step.completed_by)
      || !Array.isArray(step.evidence_links)
      || !isString(step.revision) || !isStrongEtag(step.etag)) {
    throw new Error('invalid_step_instance');
  }
  if (step.state === 'not_applicable' && !step.not_applicable_reason?.trim()) {
    throw new Error('missing_not_applicable_reason');
  }
  step.evidence_links.forEach(validateEvidenceLink);
  validateActions(step.actions);
  return step;
}

export function validateTenancyChange(value) {
  if (!isObject(value) || !isString(value.id) || !isString(value.portfolio_id)
      || !isString(value.property_id) || !isString(value.unit_id)
      || !optionalString(value.previous_contract_id) || !optionalString(value.next_contract_id)
      || !CHANGE_MODES.includes(value.mode)
      || !optionalDate(value.move_out_handover_date) || !optionalDate(value.move_in_handover_date)
      || !optionalString(value.move_out_template_version_id)
      || !optionalString(value.move_in_template_version_id)
      || !['draft', 'active', 'completed', 'cancelled'].includes(value.state)
      || !isString(value.revision) || !isStrongEtag(value.etag)
      || !isString(value.created_by) || !isTimestamp(value.created_at) || !isTimestamp(value.updated_at)
      || !isSha256(value.snapshot_sha256) || !Array.isArray(value.steps)) {
    throw new Error('invalid_tenancy_change');
  }
  value.steps.forEach(step => validateStepInstance(step, value.id));
  validateActions(value.actions);
  return value;
}

export function validateCursorPage(value, validateItem) {
  if (!isObject(value) || !Array.isArray(value.items)
      || !(value.next_cursor == null || isString(value.next_cursor))
      || typeof value.has_more !== 'boolean'
      || (value.has_more && !isString(value.next_cursor))
      || (!value.has_more && value.next_cursor != null)) {
    throw new Error('invalid_cursor_page');
  }
  value.items.forEach(validateItem);
  return value;
}

export function newWorkflowStepKey() {
  if (typeof globalThis.crypto?.randomUUID !== 'function') throw new Error('crypto.randomUUID unavailable');
  return `step-${globalThis.crypto.randomUUID()}`;
}

export function newIdempotencyKey(prefix = 'tenancy-workflow') {
  if (typeof globalThis.crypto?.randomUUID !== 'function') throw new Error('crypto.randomUUID unavailable');
  return `${prefix}:${globalThis.crypto.randomUUID()}`;
}

export function isUnknownOutcome(error) {
  const status = error?.statusCode ?? error?.status;
  return error?.isNetwork === true || (Number.isInteger(status) && status >= 500 && status <= 599);
}

export function isConflictOutcome(error) {
  const status = error?.statusCode ?? error?.status;
  return status === 409 || status === 412;
}

export function displayEvidenceReference(link) {
  if (link.kind === 'document_version') return link.document_version_id;
  return link.handover_protocol_id || link.meter_reading_id || link.reference_id || link.id;
}

export function createTemplateCommand({ property_id, unit_id = null, direction, steps }, key = newIdempotencyKey('workflow-template-create')) {
  validateTemplateDraftSteps(steps);
  return { idempotency_key: key, expected_revision: 'new', property_id, unit_id, direction, steps };
}

export function createTemplateVersionCommand(version, key = newIdempotencyKey('workflow-template-version')) {
  validateTemplateVersion(version);
  return { idempotency_key: key, expected_revision: version.revision, based_on_version_id: version.id };
}

export function updateTemplateVersionCommand(version, steps, key = newIdempotencyKey('workflow-template-update')) {
  validateTemplateVersion(version);
  validateTemplateDraftSteps(steps);
  return { idempotency_key: key, expected_revision: version.revision, steps };
}

export function publishTemplateVersionCommand(version, key = newIdempotencyKey('workflow-template-publish')) {
  validateTemplateVersion(version);
  return { idempotency_key: key, expected_revision: version.revision };
}

export function startTenancyChangeCommand(selection, preview, key = newIdempotencyKey('tenancy-change-start')) {
  if (!isObject(preview) || !isSha256(preview.preview_hash) || !isObject(preview.source_etags)) {
    throw new Error('invalid_change_preview');
  }
  return {
    idempotency_key: key,
    expected_revision: 'new',
    ...selection,
    preview_hash: preview.preview_hash,
    source_etags: { ...preview.source_etags },
  };
}

export function cancelTenancyChangeCommand(change, reason, key = newIdempotencyKey('tenancy-change-cancel')) {
  validateTenancyChange(change);
  if (!isString(reason?.trim())) throw new Error('missing_cancel_reason');
  return { idempotency_key: key, expected_revision: change.revision, state: 'cancelled', reason: reason.trim() };
}

export function reanchorPreviewPayload(change, dates) {
  validateTenancyChange(change);
  return {
    expected_revision: change.revision,
    move_out_handover_date: dates.move_out_handover_date || null,
    move_in_handover_date: dates.move_in_handover_date || null,
  };
}

export function reanchorTenancyChangeCommand(change, dates, preview, key = newIdempotencyKey('tenancy-change-reanchor')) {
  validateTenancyChange(change);
  if (!isObject(preview) || !isSha256(preview.preview_hash) || !isObject(preview.source_etags)) {
    throw new Error('invalid_reanchor_preview');
  }
  return {
    idempotency_key: key,
    expected_revision: change.revision,
    move_out_handover_date: dates.move_out_handover_date || null,
    move_in_handover_date: dates.move_in_handover_date || null,
    preview_hash: preview.preview_hash,
    source_etags: { ...preview.source_etags },
  };
}

function stepParentEnvelope(change, step, prefix, key) {
  validateTenancyChange(change);
  validateStepInstance(step, change.id);
  return {
    idempotency_key: key || newIdempotencyKey(prefix),
    expected_revision: step.revision,
    expected_change_revision: change.revision,
  };
}

export function updateStepCommand(change, step, patch, key) {
  if (!['open', 'in_progress', 'completed', 'not_applicable'].includes(patch?.state)) {
    throw new Error('invalid_step_state');
  }
  if (patch.state === 'not_applicable' && !patch.not_applicable_reason?.trim()) {
    throw new Error('missing_not_applicable_reason');
  }
  const command = { ...stepParentEnvelope(change, step, 'tenancy-step-update', key), state: patch.state };
  if (patch.state === 'not_applicable') command.not_applicable_reason = patch.not_applicable_reason.trim();
  return command;
}

export function createStepTaskCommand(change, step, key) {
  return stepParentEnvelope(change, step, 'tenancy-step-task', key);
}

export function addEvidenceCommand(change, step, evidence, key) {
  if (!isObject(evidence) || !['document_version', 'handover_protocol', 'meter_reading'].includes(evidence.kind)) {
    throw new Error('invalid_evidence_input');
  }
  if (evidence.kind === 'document_version' && (!isString(evidence.document_id) || !isString(evidence.document_version_id))) {
    throw new Error('invalid_document_evidence');
  }
  return { ...stepParentEnvelope(change, step, 'tenancy-step-evidence-add', key), evidence };
}

export function removeEvidenceCommand(change, step, key) {
  return stepParentEnvelope(change, step, 'tenancy-step-evidence-remove', key);
}

export function completeTenancyChangeCommand(change, key = newIdempotencyKey('tenancy-change-complete')) {
  validateTenancyChange(change);
  return { idempotency_key: key, expected_revision: change.revision };
}

export function validateChangePreview(value) {
  if (!isObject(value) || !isSha256(value.preview_hash) || !isSha256(value.snapshot_sha256)
      || !isObject(value.source_etags) || !isObject(value.anchors)
      || !Array.isArray(value.affected_steps) || !Array.isArray(value.conflicts)
      || !isString(value.portfolio_id)) {
    throw new Error('invalid_change_preview');
  }
  return value;
}

export function validateReanchorPreview(value, changeId, revision) {
  if (!isObject(value) || !isSha256(value.preview_hash) || value.change_revision !== revision
      || !isObject(value.source_etags) || !Array.isArray(value.affected_steps)
      || !Array.isArray(value.completed_steps_unchanged)) {
    throw new Error('invalid_reanchor_preview');
  }
  for (const item of value.affected_steps) {
    if (!isObject(item) || !isString(item.step_id)
        || !optionalDate(item.original_due_date) || !optionalDate(item.current_due_date)
        || !optionalDate(item.new_due_date) || !optionalString(item.task_id)) {
      throw new Error('invalid_reanchor_preview');
    }
  }
  if (!isString(changeId)) throw new Error('invalid_change_id');
  return value;
}
