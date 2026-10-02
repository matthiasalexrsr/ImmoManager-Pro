import { describe, expect, it } from 'vitest';
import {
  ANCHORS,
  actionAllowed,
  addEvidenceCommand,
  cancelTenancyChangeCommand,
  completeTenancyChangeCommand,
  createStepTaskCommand,
  createTemplateCommand,
  createTemplateVersionCommand,
  publishTemplateVersionCommand,
  reanchorPreviewPayload,
  reanchorTenancyChangeCommand,
  removeEvidenceCommand,
  startTenancyChangeCommand,
  updateStepCommand,
  updateTemplateVersionCommand,
  validateCursorPage,
  validateTemplateDraftSteps,
  validateTemplateVersion,
  validateTenancyChange,
} from '../features/tenancyWorkflows/tenancyWorkflowModel';

const hash = char => char.repeat(64);
const timestamp = '2026-10-02T10:00:00+00:00';

function stepInput(overrides = {}) {
  return {
    stable_key: overrides.stable_key || 'stable-step',
    position: overrides.position ?? 0,
    title: overrides.title || 'Schlüssel zählen',
    description: overrides.description ?? null,
    default_requirement: overrides.default_requirement || 'required',
    anchor: overrides.anchor || 'move_in_handover',
    offset_days: overrides.offset_days ?? 0,
    assignee_user_id: overrides.assignee_user_id ?? null,
    assignee_role: overrides.assignee_role ?? 'techniker',
    depends_on_step_keys: overrides.depends_on_step_keys || [],
    evidence_requirement: overrides.evidence_requirement || 'none',
  };
}

function templateStep(overrides = {}) {
  return { id: overrides.id || 'step-template-1', ...stepInput(overrides) };
}

function version(overrides = {}) {
  return {
    id: 'version-1',
    template_id: 'template-1',
    portfolio_id: 'portfolio-1',
    property_id: 'property-1',
    unit_id: null,
    direction: 'move_in',
    version: 3,
    state: 'draft',
    based_on_version_id: 'version-0',
    revision: 'version-rev-3',
    etag: '"immo-workflow-v1:template-version:version-1:version-rev-3"',
    created_at: timestamp,
    published_at: null,
    steps: [templateStep()],
    actions: { edit_template: true, publish_template: true },
    ...overrides,
  };
}

function evidence(overrides = {}) {
  return {
    id: 'evidence-1',
    kind: 'document_version',
    document_id: 'doc-1',
    document_version_id: 'doc-version-7',
    handover_protocol_id: null,
    meter_reading_id: null,
    snapshot_sha256: hash('e'),
    created_at: timestamp,
    ...overrides,
  };
}

function instance(overrides = {}) {
  return {
    id: 'instance-1',
    tenancy_change_id: 'change-1',
    template_step_key: 'stable-step',
    direction: 'move_in',
    title_snapshot: 'Schlüssel zählen',
    description_snapshot: null,
    requirement: 'required',
    not_applicable_reason: null,
    anchor: 'move_in_handover',
    offset_days: 0,
    original_due_date: '2026-10-10',
    due_date: '2026-10-10',
    state: 'open',
    blocked_by_step_ids: [],
    assignee_user_id: null,
    assignee_role: 'techniker',
    task_id: null,
    completed_at: null,
    completed_by: null,
    evidence_links: [],
    revision: 'step-rev-1',
    etag: '"immo-workflow-v1:step:instance-1:step-rev-1"',
    actions: { complete_step: true, link_task: true, link_document: true },
    ...overrides,
  };
}

function change(overrides = {}) {
  return {
    id: 'change-1',
    portfolio_id: 'portfolio-1',
    property_id: 'property-1',
    unit_id: 'unit-1',
    previous_contract_id: 'contract-old',
    next_contract_id: 'contract-new',
    mode: 'turnover',
    move_out_handover_date: '2026-10-09',
    move_in_handover_date: '2026-10-10',
    move_out_template_version_id: 'version-out',
    move_in_template_version_id: 'version-in',
    state: 'active',
    revision: 'change-rev-1',
    etag: '"immo-workflow-v1:tenancy-change:change-1:change-rev-1"',
    created_by: 'user-1',
    created_at: timestamp,
    updated_at: timestamp,
    snapshot_sha256: hash('a'),
    steps: [instance()],
    actions: { edit_change: true, reanchor: true, complete_change: true },
    ...overrides,
  };
}

describe('tenancy workflow source contract', () => {
  it('accepts all four separate date anchors and rejects cycles or empty templates', () => {
    for (const [index, anchor] of ANCHORS.entries()) {
      const item = version({
        steps: [templateStep({ id: `s-${index}`, stable_key: `k-${index}`, anchor })],
      });
      expect(validateTemplateVersion(item)).toBe(item);
    }

    expect(() => validateTemplateDraftSteps([])).toThrow('invalid_template_steps');
    expect(() => validateTemplateDraftSteps([
      stepInput({ stable_key: 'a', depends_on_step_keys: ['b'] }),
      stepInput({ stable_key: 'b', position: 1, depends_on_step_keys: ['a'] }),
    ])).toThrow('dependency_cycle');
  });

  it('requires exactly one template-step responsibility: concrete user or role', () => {
    expect(() => validateTemplateDraftSteps([{
      ...stepInput(),
      assignee_user_id: null,
      assignee_role: null,
    }])).toThrow('invalid_template_step');

    expect(() => validateTemplateDraftSteps([
      stepInput({ assignee_user_id: 'user-1', assignee_role: 'techniker' }),
    ])).toThrow('invalid_template_step');

    expect(validateTemplateDraftSteps([{
      ...stepInput(),
      assignee_user_id: 'user-1',
      assignee_role: null,
    }])).toHaveLength(1);
    expect(validateTemplateDraftSteps([stepInput()])).toHaveLength(1);
  });

  it('requires exact immutable evidence identity from the step response DTO', () => {
    const valid = change({ steps: [instance({ evidence_links: [evidence()] })] });
    expect(validateTenancyChange(valid)).toBe(valid);

    expect(() => validateTenancyChange(change({
      steps: [instance({ evidence_links: [evidence({ document_version_id: null })] })],
    }))).toThrow('invalid_document_evidence');
  });

  it('uses server actions without inferring workflow rights from roles', () => {
    expect(actionAllowed({ actions: { complete_step: true } }, 'complete_step')).toBe(true);
    expect(actionAllowed({ actions: { complete_step: false } }, 'complete_step')).toBe(false);
  });

  it('keeps workflow cursors opaque and does not impose a total-record cap', () => {
    const page = {
      items: [change()],
      next_cursor: 'opaque-user-role-filter-budget-token',
      has_more: true,
    };
    expect(validateCursorPage(page, validateTenancyChange)).toBe(page);
  });

  it('builds CreateTemplate with expected_revision new and the exact step list', () => {
    expect(createTemplateCommand({
      property_id: 'property-1',
      unit_id: null,
      direction: 'move_out',
      steps: [stepInput({ anchor: 'move_out_handover' })],
    }, 'create-template-key')).toEqual({
      idempotency_key: 'create-template-key',
      expected_revision: 'new',
      property_id: 'property-1',
      unit_id: null,
      direction: 'move_out',
      steps: [stepInput({ anchor: 'move_out_handover' })],
    });
  });

  it('builds template version create/update/publish against the exact version revision', () => {
    const source = version({ state: 'published' });
    expect(createTemplateVersionCommand(source, 'new-version-key')).toEqual({
      idempotency_key: 'new-version-key',
      expected_revision: 'version-rev-3',
      based_on_version_id: 'version-1',
    });
    const serverStep = {
      id: 'server-step-1',
      etag: '"step-etag"',
      created_at: timestamp,
      ...stepInput(),
    };
    expect(updateTemplateVersionCommand(version(), [serverStep], 'update-key')).toEqual({
      idempotency_key: 'update-key',
      expected_revision: 'version-rev-3',
      steps: [stepInput()],
    });
    expect(publishTemplateVersionCommand(version(), 'publish-key')).toEqual({
      idempotency_key: 'publish-key',
      expected_revision: 'version-rev-3',
    });
  });

  it('builds StartTenancyChange with expected_revision new and exact preview evidence', () => {
    const selection = {
      property_id: 'property-1',
      unit_id: 'unit-1',
      previous_contract_id: 'contract-old',
      next_contract_id: 'contract-new',
      mode: 'turnover',
      move_out_handover_date: '2026-10-09',
      move_in_handover_date: '2026-10-10',
      move_out_template_version_id: 'version-out',
      move_in_template_version_id: 'version-in',
    };
    const preview = {
      preview_hash: hash('b'),
      source_etags: { previous_contract: '"old"', next_contract: '"new"' },
    };
    expect(startTenancyChangeCommand(selection, preview, 'start-key')).toEqual({
      idempotency_key: 'start-key',
      expected_revision: 'new',
      ...selection,
      preview_hash: hash('b'),
      source_etags: preview.source_etags,
    });
  });

  it('binds every step/task/evidence command to step and parent change revisions', () => {
    const current = change();
    const step = current.steps[0];
    const both = {
      expected_revision: 'step-rev-1',
      expected_change_revision: 'change-rev-1',
    };

    expect(updateStepCommand(current, step, { state: 'completed' }, 'step-key'))
      .toEqual({ idempotency_key: 'step-key', ...both, state: 'completed' });
    expect(createStepTaskCommand(current, step, 'task-key'))
      .toEqual({ idempotency_key: 'task-key', ...both });
    expect(addEvidenceCommand(current, step, {
      kind: 'document_version',
      document_id: 'doc-1',
      document_version_id: 'version-9',
    }, 'evidence-key')).toEqual({
      idempotency_key: 'evidence-key',
      ...both,
      evidence: {
        kind: 'document_version',
        document_id: 'doc-1',
        document_version_id: 'version-9',
      },
    });
    expect(removeEvidenceCommand(current, step, 'remove-key'))
      .toEqual({ idempotency_key: 'remove-key', ...both });
  });

  it('builds explicit cancellation with the current change revision and nonblank reason', () => {
    expect(cancelTenancyChangeCommand(change(), 'Bewusst abgebrochen', 'cancel-key')).toEqual({
      idempotency_key: 'cancel-key',
      expected_revision: 'change-rev-1',
      state: 'cancelled',
      reason: 'Bewusst abgebrochen',
    });
    expect(() => cancelTenancyChangeCommand(change(), '   ', 'cancel-key')).toThrow('missing_cancel_reason');
  });

  it('uses the change revision for reanchor preview/confirm and complete', () => {
    const current = change();
    const dates = {
      move_out_handover_date: '2026-10-12',
      move_in_handover_date: '2026-10-13',
    };
    expect(reanchorPreviewPayload(current, dates)).toEqual({
      expected_revision: 'change-rev-1',
      ...dates,
    });

    const preview = {
      preview_hash: hash('c'),
      source_etags: { previous_contract: '"old"', next_contract: '"new"' },
    };
    expect(reanchorTenancyChangeCommand(current, dates, preview, 'reanchor-key')).toEqual({
      idempotency_key: 'reanchor-key',
      expected_revision: 'change-rev-1',
      ...dates,
      preview_hash: hash('c'),
      source_etags: preview.source_etags,
    });
    expect(completeTenancyChangeCommand(current, 'complete-key')).toEqual({
      idempotency_key: 'complete-key',
      expected_revision: 'change-rev-1',
    });
  });
});
