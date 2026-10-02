import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import TenancyChangeFile from '../features/tenancyWorkflows/TenancyChangeFile';
import {
  addEvidenceCommand,
  cancelTenancyChangeCommand,
  reanchorTenancyChangeCommand,
  removeEvidenceCommand,
  updateStepCommand,
} from '../features/tenancyWorkflows/tenancyWorkflowModel';

const hash = char => char.repeat(64);
const timestamp = '2026-10-02T10:00:00+00:00';

function evidence(overrides = {}) {
  return {
    id: 'evidence-1',
    kind: 'document_version',
    document_id: 'document-1',
    document_version_id: 'document-version-7',
    handover_protocol_id: null,
    meter_reading_id: null,
    snapshot_sha256: hash('e'),
    created_at: timestamp,
    ...overrides,
  };
}

function step(overrides = {}) {
  return {
    id: overrides.id || 'step-1',
    tenancy_change_id: 'change-1',
    template_step_key: overrides.template_step_key || 'key-1',
    direction: overrides.direction || 'move_out',
    title_snapshot: overrides.title_snapshot || 'Übergabeprotokoll erstellen',
    description_snapshot: null,
    requirement: overrides.requirement || 'required',
    not_applicable_reason: overrides.not_applicable_reason ?? null,
    anchor: overrides.anchor || 'move_out_handover',
    offset_days: overrides.offset_days ?? -1,
    original_due_date: overrides.original_due_date || '2026-10-09',
    due_date: overrides.due_date || '2026-10-12',
    state: overrides.state || 'open',
    blocked_by_step_ids: overrides.blocked_by_step_ids || [],
    assignee_user_id: null,
    assignee_role: 'techniker',
    task_id: overrides.task_id ?? null,
    completed_at: overrides.completed_at ?? null,
    completed_by: overrides.completed_by ?? null,
    evidence_links: overrides.evidence_links || [],
    revision: overrides.revision || 'step-rev-1',
    etag: overrides.etag || '"immo-workflow-v1:step:step-1:step-rev-1"',
    actions: overrides.actions || { complete_step: true, link_task: true, link_document: true },
    ...overrides,
  };
}

function change(overrides = {}) {
  return {
    id: 'change-1',
    portfolio_id: 'portfolio-1',
    property_id: 'property-1',
    unit_id: 'unit-1',
    previous_contract_id: 'old-contract',
    next_contract_id: 'new-contract',
    mode: 'turnover',
    move_out_handover_date: '2026-10-10',
    move_in_handover_date: '2026-10-11',
    move_out_template_version_id: 'out-version',
    move_in_template_version_id: 'in-version',
    state: 'active',
    revision: overrides.revision || 'change-rev-1',
    etag: overrides.etag || '"immo-workflow-v1:tenancy-change:change-1:change-rev-1"',
    created_by: 'manager-1',
    created_at: timestamp,
    updated_at: timestamp,
    snapshot_sha256: hash('c'),
    steps: overrides.steps || [step()],
    actions: overrides.actions || { edit_change: true, reanchor: true, complete_change: true },
    ...overrides,
  };
}

function nextChange(source, steps, revision = 'change-rev-2') {
  return change({
    ...source,
    revision,
    etag: `"immo-workflow-v1:tenancy-change:change-1:${revision}"`,
    updated_at: '2026-10-02T11:00:00+00:00',
    steps,
  });
}

describe('TenancyChangeFile against the core DTOs', () => {
  it('shows original/current due dates, blocking facts, real task ids and immutable document versions', () => {
    const blocked = step({
      state: 'blocked',
      blocked_by_step_ids: ['step-before'],
      task_id: 'task-real-42',
      evidence_links: [evidence()],
      actions: { complete_step: false, link_task: false, link_document: false },
    });
    render(<TenancyChangeFile change={change({ steps: [blocked] })} onOpenTask={vi.fn()} />);

    expect(screen.getByText('2026-10-12')).toBeInTheDocument();
    expect(screen.getByText('2026-10-09')).toBeInTheDocument();
    expect(screen.getByText(/step-before/)).toBeInTheDocument();
    expect(screen.getByText('document-version-7')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Aufgabe öffnen · task-real-42/ })).toBeInTheDocument();
  });

  it('prepares not-applicable with the step revision and parent change revision', async () => {
    const source = change();
    const prepareStepMutation = vi.fn(({ change: current, step: currentStep, patch }) => ({
      payload: updateStepCommand(current, currentStep, patch, 'step-command'),
      send: vi.fn(async () => nextChange(current, [{
        ...currentStep,
        ...patch,
        revision: 'step-rev-2',
        etag: '"immo-workflow-v1:step:step-1:step-rev-2"',
        completed_at: timestamp,
        completed_by: 'manager-1',
      }])),
    }));
    render(<TenancyChangeFile change={source} prepareStepMutation={prepareStepMutation} />);

    const exception = screen.getByText('Begründung der Ausnahme').closest('.workflow-not-applicable');
    const button = within(exception).getByRole('button', { name: 'Als unzutreffend markieren' });
    expect(button).toBeDisabled();
    fireEvent.change(within(exception).getByRole('textbox'), {
      target: { value: 'Kein Schlüsselbestand vorhanden' },
    });
    fireEvent.click(button);

    await waitFor(() => expect(prepareStepMutation).toHaveBeenCalledTimes(1));
    const prepared = prepareStepMutation.mock.results[0].value.payload;
    expect(prepared).toEqual({
      idempotency_key: 'step-command',
      expected_revision: 'step-rev-1',
      expected_change_revision: 'change-rev-1',
      state: 'not_applicable',
      not_applicable_reason: 'Kein Schlüsselbestand vorhanden',
    });
  });

  it('reanchors only from a current preview and preserves completed original facts', async () => {
    const completed = step({
      id: 'done',
      template_step_key: 'done-key',
      state: 'completed',
      title_snapshot: 'Bereits erledigt',
      original_due_date: '2026-10-08',
      due_date: '2026-10-08',
      completed_at: '2026-10-08T12:00:00+00:00',
      completed_by: 'user-1',
      revision: 'done-rev',
      etag: '"immo-workflow-v1:step:done:done-rev"',
      actions: { complete_step: false, link_task: false, link_document: false },
    });
    const open = step({ id: 'open', template_step_key: 'open-key', title_snapshot: 'Noch offen' });
    const source = change({ steps: [completed, open] });
    const preview = {
      preview_hash: hash('f'),
      change_revision: 'change-rev-1',
      source_etags: { previous_contract: '"old"', next_contract: '"new"' },
      affected_steps: [{
        step_id: 'open',
        original_due_date: '2026-10-09',
        current_due_date: '2026-10-12',
        new_due_date: '2026-10-17',
        task_id: null,
      }],
      completed_steps_unchanged: ['done'],
    };
    const onReanchorPreview = vi.fn(async () => preview);
    const prepareReanchor = vi.fn(({ change: current, dates, preview: accepted }) => ({
      payload: reanchorTenancyChangeCommand(current, dates, accepted, 'reanchor-key'),
      send: vi.fn(async () => nextChange(current, [
        completed,
        {
          ...open,
          due_date: '2026-10-17',
          revision: 'step-open-2',
          etag: '"immo-workflow-v1:step:open:step-open-2"',
        },
      ])),
    }));

    render(<TenancyChangeFile change={source}
      onReanchorPreview={onReanchorPreview} prepareReanchor={prepareReanchor} />);
    fireEvent.click(screen.getByRole('button', { name: 'Übergabetermine ändern' }));
    fireEvent.change(screen.getByLabelText('Auszugsübergabe'), { target: { value: '2026-10-15' } });
    fireEvent.click(screen.getByRole('button', { name: 'Verschiebung prüfen' }));

    expect(await screen.findByText(hash('f'))).toBeInTheDocument();
    expect(screen.getByText(/2026-10-12 → 2026-10-17/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Bestätigte Verschiebung anwenden' }));

    await waitFor(() => expect(prepareReanchor).toHaveBeenCalledTimes(1));
    expect(prepareReanchor.mock.results[0].value.payload).toMatchObject({
      idempotency_key: 'reanchor-key',
      expected_revision: 'change-rev-1',
      preview_hash: hash('f'),
      source_etags: preview.source_etags,
      move_out_handover_date: '2026-10-15',
    });
    expect(screen.getByText(/Erledigt am/)).toBeInTheDocument();
  });

  it('cancels only with an explicit reason and the current change revision', async () => {
    const source = change();
    const prepareCancel = vi.fn(({ change: current, reason }) => ({
      payload: cancelTenancyChangeCommand(current, reason, 'cancel-key'),
      send: vi.fn(async () => change({
        ...current,
        state: 'cancelled',
        revision: 'change-rev-2',
        etag: '"immo-workflow-v1:tenancy-change:change-1:change-rev-2"',
        actions: { edit_change: false, reanchor: false, complete_change: false },
      })),
    }));

    render(<TenancyChangeFile change={source} prepareCancel={prepareCancel} />);
    const button = screen.getByRole('button', { name: 'Wechselakte abbrechen' });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Grund des Abbruchs'), {
      target: { value: 'Vorgang bewusst verworfen' },
    });
    fireEvent.click(button);

    await waitFor(() => expect(prepareCancel).toHaveBeenCalledTimes(1));
    expect(prepareCancel.mock.results[0].value.payload).toEqual({
      idempotency_key: 'cancel-key',
      expected_revision: 'change-rev-1',
      state: 'cancelled',
      reason: 'Vorgang bewusst verworfen',
    });
  });

  it('links an immutable document version with the current step and change revisions', async () => {
    const source = change();
    const linkedStep = {
      ...source.steps[0],
      revision: 'step-rev-2',
      etag: '"immo-workflow-v1:step:step-1:step-rev-2"',
      evidence_links: [evidence()],
    };
    const linkedChange = nextChange(source, [linkedStep], 'change-rev-2');

    const prepareEvidenceLink = vi.fn(({ change: current, step: currentStep, selection }) => ({
      payload: addEvidenceCommand(current, currentStep, {
        kind: 'document_version',
        document_id: selection.document_id,
        document_version_id: selection.document_version_id,
      }, 'add-evidence-key'),
      send: vi.fn(async () => linkedChange),
    }));
    const loadDocuments = vi.fn(async () => ({
      items: [{
        id: 'document-1',
        title: 'Übergabe Original',
        property_id: 'property-1',
        unit_id: 'unit-1',
        contract_id: 'old-contract',
      }],
      next_cursor: null,
      has_more: false,
      selected: null,
    }));
    render(<TenancyChangeFile change={source}
      prepareEvidenceLink={prepareEvidenceLink}
      loadDocuments={loadDocuments}
      loadDocumentVersions={async documentId => ({
        document_id: documentId,
        items: [{
          id: 'document-version-7',
          number: 7,
          filename: 'original.pdf',
          sha256: hash('d'),
          created_at: timestamp,
        }],
        next_before: null,
      })}
      canSelectEvidence={() => true}
    />);

    fireEvent.click(screen.getByRole('button', { name: 'Beleg verknüpfen' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(await within(dialog).findByRole('option', { name: /Übergabe Original/ }));
    fireEvent.click(await within(dialog).findByRole('radio', { name: /v7 · original.pdf/ }));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Beleg verknüpfen' }));

    expect(loadDocuments).toHaveBeenCalledWith(expect.objectContaining({
      propertyId: 'property-1',
      unitId: 'unit-1',
      contractId: 'old-contract',
      cursor: null,
      search: '',
      selectedId: null,
      limit: 25,
      signal: expect.any(AbortSignal),
    }));
    await waitFor(() => expect(prepareEvidenceLink).toHaveBeenCalledTimes(1));
    expect(prepareEvidenceLink.mock.results[0].value.payload).toEqual({
      idempotency_key: 'add-evidence-key',
      expected_revision: 'step-rev-1',
      expected_change_revision: 'change-rev-1',
      evidence: {
        kind: 'document_version',
        document_id: 'document-1',
        document_version_id: 'document-version-7',
      },
    });
  });

  it('loads a finalized meter reading through the canonical scoped reference flow', async () => {
    const meterStep = step({
      evidence_requirement: 'meter_reading',
      direction: 'move_out',
    });
    const source = change({ steps: [meterStep] });
    const loadMeterReadings = vi.fn(async () => ({
      items: [{
        id: 'reading-1',
        meter_number: 'W-17',
        reading_value: '321.5',
        unit: 'm³',
      }],
      next_cursor: null,
      has_more: false,
      selected: null,
    }));
    const prepareEvidenceLink = vi.fn(({ change: current, step: currentStep, selection }) => ({
      payload: addEvidenceCommand(current, currentStep, {
        kind: 'meter_reading',
        meter_reading_id: selection.item.id,
      }, 'meter-evidence-key'),
      send: vi.fn(async () => nextChange(current, [{
        ...currentStep,
        revision: 'step-rev-2',
        etag: '"immo-workflow-v1:step:step-1:step-rev-2"',
      }])),
    }));

    render(<TenancyChangeFile
      change={source}
      prepareEvidenceLink={prepareEvidenceLink}
      loadMeterReadings={loadMeterReadings}
      canSelectEvidence={() => true}
    />);

    fireEvent.click(screen.getByRole('button', { name: 'Beleg verknüpfen' }));
    const dialog = await screen.findByRole('dialog');
    const reading = await within(dialog).findByRole('option', { name: /W-17/ });
    fireEvent.click(reading);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Beleg verknüpfen' }));

    expect(loadMeterReadings).toHaveBeenCalledWith(expect.objectContaining({
      propertyId: 'property-1',
      unitId: 'unit-1',
      contractId: 'old-contract',
      direction: 'move_out',
      cursor: null,
      search: '',
      selectedId: null,
      limit: 25,
    }));
    await waitFor(() => expect(prepareEvidenceLink).toHaveBeenCalledTimes(1));
    expect(prepareEvidenceLink.mock.results[0].value.payload).toEqual({
      idempotency_key: 'meter-evidence-key',
      expected_revision: 'step-rev-1',
      expected_change_revision: 'change-rev-1',
      evidence: {
        kind: 'meter_reading',
        meter_reading_id: 'reading-1',
      },
    });
  });

  it('removes an existing evidence link with the freshly read step and change revisions', async () => {
    const linkedStep = step({
      revision: 'step-rev-2',
      etag: '"immo-workflow-v1:step:step-1:step-rev-2"',
      evidence_links: [evidence()],
    });
    const linkedChange = change({
      revision: 'change-rev-2',
      etag: '"immo-workflow-v1:tenancy-change:change-1:change-rev-2"',
      steps: [linkedStep],
    });
    const prepareUnlinkEvidence = vi.fn(({ change: current, step: currentStep }) => ({
      payload: removeEvidenceCommand(current, currentStep, 'remove-evidence-key'),
      send: vi.fn(async () => nextChange(current, [{
        ...currentStep,
        revision: 'step-rev-3',
        etag: '"immo-workflow-v1:step:step-1:step-rev-3"',
        evidence_links: [],
      }], 'change-rev-3')),
    }));

    render(<TenancyChangeFile change={linkedChange}
      prepareUnlinkEvidence={prepareUnlinkEvidence} />);

    expect(screen.getByText('document-version-7')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '×' }));
    await waitFor(() => expect(prepareUnlinkEvidence).toHaveBeenCalledTimes(1));
    expect(prepareUnlinkEvidence.mock.results[0].value.payload).toEqual({
      idempotency_key: 'remove-evidence-key',
      expected_revision: 'step-rev-2',
      expected_change_revision: 'change-rev-2',
    });
  });
});
