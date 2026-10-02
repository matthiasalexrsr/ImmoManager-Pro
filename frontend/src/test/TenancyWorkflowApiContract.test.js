import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
  delJson: vi.fn(),
}));

vi.mock('../api', () => ({ api: apiMock }));

import { workflowApi, workflowReferenceLoader } from '../features/tenancyWorkflows/tenancyWorkflowApi';

const hash = char => char.repeat(64);
const timestamp = '2026-10-02T10:00:00+00:00';

const templateStep = {
  id: 'template-step-1',
  stable_key: 'keys',
  position: 0,
  title: 'Schlüssel',
  description: null,
  default_requirement: 'required',
  anchor: 'move_in_handover',
  offset_days: 0,
  assignee_user_id: null,
  assignee_role: 'techniker',
  depends_on_step_keys: [],
  evidence_requirement: 'none',
};

const version = {
  id: 'version-1',
  template_id: 'template-1',
  portfolio_id: 'portfolio-1',
  property_id: 'property-1',
  unit_id: null,
  direction: 'move_in',
  version: 1,
  state: 'draft',
  based_on_version_id: null,
  revision: 'version-rev-1',
  etag: '"immo-workflow-v1:template-version:version-1:version-rev-1"',
  created_at: timestamp,
  published_at: null,
  steps: [templateStep],
  actions: { edit_template: true, publish_template: true },
};

const workflowStep = {
  id: 'step-1',
  tenancy_change_id: 'change-1',
  template_step_key: 'keys',
  direction: 'move_in',
  title_snapshot: 'Schlüssel',
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
  etag: '"immo-workflow-v1:step:step-1:step-rev-1"',
  actions: { complete_step: true, link_task: true, link_document: true },
};

const change = {
  id: 'change-1',
  portfolio_id: 'portfolio-1',
  property_id: 'property-1',
  unit_id: 'unit-1',
  previous_contract_id: null,
  next_contract_id: 'contract-new',
  mode: 'move_in',
  move_out_handover_date: null,
  move_in_handover_date: '2026-10-10',
  move_out_template_version_id: null,
  move_in_template_version_id: 'version-1',
  state: 'active',
  revision: 'change-rev-1',
  etag: '"immo-workflow-v1:tenancy-change:change-1:change-rev-1"',
  created_by: 'user-1',
  created_at: timestamp,
  updated_at: timestamp,
  snapshot_sha256: hash('a'),
  steps: [workflowStep],
  actions: { edit_change: true, reanchor: true, complete_change: true },
};

describe('tenancy workflow API contract', () => {
  beforeEach(() => vi.clearAllMocks());

  it('sends canonical reference search filters, selected_id and opaque cursor without a total cap', async () => {
    const response = {
      items: [{ id: 'user-2', full_name: 'Technik Zwei', role: 'techniker' }],
      next_cursor: 'opaque-ref-next',
      has_more: true,
      selected: { id: 'user-1', full_name: 'Technik Eins', role: 'techniker' },
    };
    apiMock.get.mockResolvedValue(response);
    const loadUsers = workflowReferenceLoader('users', { property_id: 'property-1' });

    expect(await loadUsers({
      search: 'technik',
      selectedId: 'user-1',
      cursor: 'opaque-ref-current',
      limit: 25,
    })).toBe(response);
    expect(apiMock.get).toHaveBeenCalledWith(
      '/workflow-references/users?search=technik&property_id=property-1&selected_id=user-1&cursor=opaque-ref-current&page_size=25',
      { signal: undefined },
    );
  });

  it('uses the opaque template cursor and treats list/create responses as WorkflowTemplateVersion', async () => {
    apiMock.get.mockResolvedValue({
      items: [version],
      next_cursor: 'opaque-next',
      has_more: true,
    });
    const page = await workflowApi.listTemplates(
      { property_id: 'property-1', direction: 'move_in' },
      { after: 'opaque-current', limit: 25 },
    );
    expect(apiMock.get).toHaveBeenCalledWith(
      '/workflow-templates?property_id=property-1&direction=move_in&after=opaque-current&limit=25',
      { signal: undefined },
    );
    expect(page.items[0]).toBe(version);

    apiMock.post.mockResolvedValue(version);
    const command = {
      idempotency_key: 'create-key',
      expected_revision: 'new',
      property_id: 'property-1',
      unit_id: null,
      direction: 'move_in',
      steps: [templateStep],
    };
    expect(await workflowApi.createTemplate(command)).toBe(version);
    expect(apiMock.post).toHaveBeenCalledWith('/workflow-templates', command, { signal: undefined });
  });

  it('validates the actual start preview response and returns a full TenancyChange after start', async () => {
    const preview = {
      preview_hash: hash('b'),
      snapshot_sha256: hash('c'),
      source_etags: { next_contract: '"contract-etag"' },
      anchors: {
        previous_contract_end: null,
        next_contract_start: '2026-10-01',
        move_out_handover: null,
        move_in_handover: '2026-10-10',
      },
      affected_steps: [{ template_step_key: 'keys', title: 'Schlüssel', due_date: '2026-10-10' }],
      conflicts: [],
      portfolio_id: 'portfolio-1',
    };
    apiMock.post.mockResolvedValueOnce(preview).mockResolvedValueOnce(change);

    const selection = {
      property_id: 'property-1',
      unit_id: 'unit-1',
      previous_contract_id: null,
      next_contract_id: 'contract-new',
      mode: 'move_in',
      move_out_handover_date: null,
      move_in_handover_date: '2026-10-10',
      move_out_template_version_id: null,
      move_in_template_version_id: 'version-1',
    };
    expect(await workflowApi.previewChange(selection)).toBe(preview);
    expect(apiMock.post).toHaveBeenNthCalledWith(1, '/tenancy-changes/preview', selection, { signal: undefined });

    const command = {
      idempotency_key: 'start-key',
      expected_revision: 'new',
      ...selection,
      preview_hash: preview.preview_hash,
      source_etags: preview.source_etags,
    };
    expect(await workflowApi.createChange(command)).toBe(change);
    expect(apiMock.post).toHaveBeenNthCalledWith(2, '/tenancy-changes', command, { signal: undefined });
  });

  it('sends the explicit cancellation PATCH and validates the full change response', async () => {
    const cancelled = {
      ...change,
      state: 'cancelled',
      revision: 'change-rev-2',
      etag: '"immo-workflow-v1:tenancy-change:change-1:change-rev-2"',
      actions: { edit_change: false, reanchor: false, complete_change: false },
    };
    const command = {
      idempotency_key: 'cancel-key',
      expected_revision: 'change-rev-1',
      state: 'cancelled',
      reason: 'Bewusst abgebrochen',
    };
    apiMock.patch.mockResolvedValue(cancelled);

    expect(await workflowApi.patchChange('change-1', command)).toBe(cancelled);
    expect(apiMock.patch).toHaveBeenCalledWith(
      '/tenancy-changes/change-1',
      command,
      { signal: undefined },
    );
  });

  it('uses the exact reanchor preview response and step mutation route', async () => {
    const preview = {
      preview_hash: hash('d'),
      change_revision: 'change-rev-1',
      source_etags: { next_contract: '"contract-etag"' },
      affected_steps: [{
        step_id: 'step-1',
        original_due_date: '2026-10-10',
        current_due_date: '2026-10-10',
        new_due_date: '2026-10-12',
        task_id: null,
      }],
      completed_steps_unchanged: [],
    };
    apiMock.post.mockResolvedValue(preview);
    const input = {
      expected_revision: 'change-rev-1',
      move_out_handover_date: null,
      move_in_handover_date: '2026-10-12',
    };
    expect(await workflowApi.reanchorPreview(change, input)).toBe(preview);
    expect(apiMock.post).toHaveBeenCalledWith(
      '/tenancy-changes/change-1/reanchor-preview',
      input,
      { signal: undefined },
    );

    const command = {
      idempotency_key: 'step-key',
      expected_revision: 'step-rev-1',
      expected_change_revision: 'change-rev-1',
      state: 'completed',
    };
    apiMock.patch.mockResolvedValue({ ...workflowStep, state: 'completed' });
    const result = await workflowApi.patchStep('change-1', 'step-1', command);
    expect(result.state).toBe('completed');
    expect(apiMock.patch).toHaveBeenCalledWith(
      '/tenancy-changes/change-1/steps/step-1',
      command,
      { signal: undefined },
    );
  });

  it('sends RemoveEvidence as a DELETE JSON body and accepts the updated Step response', async () => {
    const command = {
      idempotency_key: 'remove-key',
      expected_revision: 'step-rev-2',
      expected_change_revision: 'change-rev-2',
    };
    apiMock.delJson.mockResolvedValue({ ...workflowStep, revision: 'step-rev-3' });
    const result = await workflowApi.unlinkEvidence(
      'change-1',
      'step-1',
      'evidence-1',
      command,
    );
    expect(result.revision).toBe('step-rev-3');
    expect(apiMock.delJson).toHaveBeenCalledWith(
      '/tenancy-changes/change-1/steps/step-1/evidence/evidence-1',
      command,
      { signal: undefined },
    );
  });
});
