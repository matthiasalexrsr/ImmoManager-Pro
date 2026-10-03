import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import WorkflowTemplateCreateForm from '../features/tenancyWorkflows/WorkflowTemplateCreateForm';
import { createTemplateCommand } from '../features/tenancyWorkflows/tenancyWorkflowModel';

describe('WorkflowTemplateCreateForm', () => {
  it('creates the first draft version with expected_revision new and an explicit task-capable role', async () => {
    const onCreated = vi.fn();
    const send = vi.fn(async payload => ({
      id: 'version-1',
      template_id: 'template-1',
      property_id: payload.property_id,
      unit_id: payload.unit_id,
      direction: payload.direction,
      version: 1,
      state: 'draft',
      revision: 'version-rev-1',
      steps: payload.steps,
    }));
    const prepareCreate = vi.fn(input => ({
      payload: createTemplateCommand(input, 'create-template-key'),
      send,
    }));

    render(<WorkflowTemplateCreateForm
      propertyLoader={async () => ({
        items: [{ id: 'property-1', name: 'Haus A' }],
        next_cursor: null,
        has_more: false,
        selected: null,
      })}
      unitLoaderForProperty={() => async () => ({
        items: [],
        next_cursor: null,
        has_more: false,
        selected: null,
      })}
      userLoaderForProperty={() => async () => ({
        items: [],
        next_cursor: null,
        has_more: false,
        selected: null,
      })}
      prepareCreate={prepareCreate}
      onCreated={onCreated}
    />);

    const properties = await screen.findByRole('listbox', { name: /Objekt/ });
    fireEvent.click(within(properties).getByRole('option', { name: 'Haus A' }));
    expect(screen.queryByLabelText('Stabiler Schlüssel')).not.toBeInTheDocument();
    const technical = screen.getByText('Technische Details').closest('details');
    expect(technical).not.toHaveAttribute('open');
    fireEvent.click(within(technical).getByText('Technische Details'));
    const generatedKey = within(technical).getByText(/^step-/).textContent;

    fireEvent.change(screen.getByLabelText('Titel'), { target: { value: 'Vorbereitung' } });
    fireEvent.change(screen.getByLabelText('Titel'), { target: { value: 'Schlüssel übernehmen' } });
    const role = screen.getByLabelText('Rolle auswählen');
    expect(within(role).getByRole('option', { name: 'Technik' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Vorlage anlegen' }));
    await waitFor(() => expect(prepareCreate).toHaveBeenCalledTimes(1));

    const payload = prepareCreate.mock.results[0].value.payload;
    expect(payload).toMatchObject({
      idempotency_key: 'create-template-key',
      expected_revision: 'new',
      property_id: 'property-1',
      unit_id: null,
      direction: 'move_in',
      steps: [{
        stable_key: generatedKey,
        position: 0,
        title: 'Schlüssel übernehmen',
        default_requirement: 'required',
        anchor: 'move_in_handover',
        offset_days: 0,
        assignee_user_id: null,
        assignee_role: 'techniker',
        depends_on_step_keys: [],
        evidence_requirement: 'none',
      }],
    });
    await waitFor(() => expect(send).toHaveBeenCalledWith(
      expect.objectContaining({ expected_revision: 'new' }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    ));
    expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({
      id: 'version-1',
      template_id: 'template-1',
    }));
  });
});
