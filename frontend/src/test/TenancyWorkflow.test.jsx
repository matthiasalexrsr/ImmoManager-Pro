import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const workflow = vi.hoisted(() => ({
  listTemplates: vi.fn(), listChanges: vi.fn(), getChange: vi.fn(), completeChange: vi.fn(),
  listTemplateVersions: vi.fn(), getTemplateVersion: vi.fn(), updateTemplateVersion: vi.fn(),
  publishTemplateVersion: vi.fn(), createTemplate: vi.fn(), previewChange: vi.fn(), createChange: vi.fn(),
  patchStep: vi.fn(),
}));

vi.mock('../tenancyWorkflowApi', async importOriginal => {
  const actual = await importOriginal();
  return { ...actual, tenancyWorkflowApi: workflow };
});

const rawApi = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('../api', () => ({ api: { get: rawApi.get } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: 'de-DE' }) }));

import TenancyWorkflows from '../pages/TenancyWorkflows';
import CursorReferencePicker from '../components/CursorReferencePicker';
import { createCommand, isReviewRequired, isUnknownOutcome } from '../tenancyWorkflowApi';

const page = (items = []) => ({ items, next_cursor: null, has_more: false });
const changeSummary = {
  id: 'change-1', property_id: 'property-1', unit_id: 'unit-1', mode: 'turnover', state: 'active',
};
const changeDetail = {
  ...changeSummary, revision: 'rev-1', etag: '"change-1"', actions: { complete_change: true },
  move_out_handover_date: '2026-10-31', move_in_handover_date: '2026-11-01',
  steps: [{
    id: 'step-1', tenancy_change_id: 'change-1', template_step_key: 'keys', direction: 'move_out',
    title_snapshot: 'Schlüssel zählen', description_snapshot: null, requirement: 'required',
    not_applicable_reason: null, anchor: 'move_out_handover', offset_days: 0,
    original_due_date: '2026-10-31', due_date: '2026-10-31', state: 'open',
    blocked_by_step_ids: [], assignee_user_id: null, assignee_role: 'techniker',
    task_id: 'task-1', completed_at: null, completed_by: null, evidence_links: [],
    revision: 'step-rev-1', etag: '"step-1"', actions: { complete_step: true },
  }],
};

describe('tenancy workflow contract UI', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    workflow.listTemplates.mockResolvedValue(page());
    workflow.listChanges.mockResolvedValue(page([changeSummary]));
    workflow.getChange.mockResolvedValue(changeDetail);
    workflow.listTemplateVersions.mockResolvedValue(page());
    rawApi.get.mockResolvedValue([]);
  });

  it('preserves the exact command after an unknown completion outcome', async () => {
    const failure = Object.assign(new Error('offline'), { isNetwork: true });
    workflow.completeChange.mockRejectedValueOnce(failure).mockResolvedValueOnce({ ...changeDetail, state: 'completed' });

    render(<TenancyWorkflows />);
    const card = await screen.findByRole('button', { name: /Aus- und Einzug/ });
    fireEvent.click(card);
    await screen.findByText('Schlüssel zählen');

    fireEvent.click(screen.getByRole('button', { name: 'Akte abschließen' }));
    await screen.findByText(/Serverergebnis unklar/);
    expect(workflow.completeChange).toHaveBeenCalledTimes(1);
    const firstPayload = workflow.completeChange.mock.calls[0][1];

    fireEvent.click(screen.getByRole('button', { name: 'Exakten Befehl erneut senden' }));
    await waitFor(() => expect(workflow.completeChange).toHaveBeenCalledTimes(2));
    expect(workflow.completeChange.mock.calls[1][1]).toBe(firstPayload);
    expect(firstPayload.expected_revision).toBe('rev-1');
    expect(firstPayload.idempotency_key).toEqual(expect.any(String));
  });

  it('sends step completion through the workflow action with the step revision', async () => {
    workflow.patchStep.mockResolvedValue({ ...changeDetail.steps[0], state: 'completed' });
    workflow.getChange.mockResolvedValueOnce(changeDetail).mockResolvedValueOnce({
      ...changeDetail, steps: [{ ...changeDetail.steps[0], state: 'completed' }],
    });

    render(<TenancyWorkflows />);
    fireEvent.click(await screen.findByRole('button', { name: /Aus- und Einzug/ }));
    await screen.findByText('Schlüssel zählen');
    fireEvent.click(screen.getByRole('button', { name: 'Abgeschlossen' }));

    await waitFor(() => expect(workflow.patchStep).toHaveBeenCalledTimes(1));
    const [changeId, stepId, payload] = workflow.patchStep.mock.calls[0];
    expect([changeId, stepId]).toEqual(['change-1', 'step-1']);
    expect(payload).toMatchObject({ expected_revision: 'step-rev-1', state: 'completed' });
    expect(payload.idempotency_key).toEqual(expect.any(String));
  });

  it('loads bounded reference pages and follows the supplied cursor', async () => {
    const loader = vi.fn()
      .mockResolvedValueOnce({ items: [{ id: 'u1', label: '1. OG' }], next_cursor: 'opaque-2', has_more: true })
      .mockResolvedValueOnce({ items: [{ id: 'u2', label: '2. OG' }], next_cursor: null, has_more: false });
    render(<CursorReferencePicker label="Einheit" value={null} onChange={() => {}} loadPage={loader} getLabel={item => item.label} />);
    await screen.findByRole('option', { name: '1. OG' });
    fireEvent.click(screen.getByRole('button', { name: 'Mehr' }));
    await screen.findByRole('option', { name: '2. OG' });
    expect(loader.mock.calls[1][0]).toMatchObject({ after: 'opaque-2', limit: 25 });
  });

  it('classifies conflicts and unknown outcomes without silent replay', () => {
    expect(isUnknownOutcome({ isNetwork: true })).toBe(true);
    expect(isUnknownOutcome({ statusCode: 503 })).toBe(true);
    expect(isReviewRequired({ statusCode: 409 })).toBe(true);
    expect(isReviewRequired({ statusCode: 412 })).toBe(true);
    const command = createCommand({ preview_hash: 'hash-1' }, 'rev-7', 'idem-1');
    expect(command).toEqual({ idempotency_key: 'idem-1', expected_revision: 'rev-7', preview_hash: 'hash-1' });
  });
});
