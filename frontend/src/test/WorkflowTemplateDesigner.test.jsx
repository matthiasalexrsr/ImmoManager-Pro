import { useState } from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import WorkflowTemplateDesigner from '../features/tenancyWorkflows/WorkflowTemplateDesigner';
import {
  publishTemplateVersionCommand,
  updateTemplateVersionCommand,
} from '../features/tenancyWorkflows/tenancyWorkflowModel';

function templateStep(overrides = {}) {
  return {
    id: overrides.id || 'step-a',
    stable_key: overrides.stable_key || 'a',
    position: overrides.position ?? 0,
    title: overrides.title || 'Termin abstimmen',
    description: null,
    default_requirement: 'required',
    anchor: overrides.anchor || 'move_out_handover',
    offset_days: 0,
    assignee_user_id: null,
    assignee_role: 'techniker',
    depends_on_step_keys: overrides.depends_on_step_keys || [],
    evidence_requirement: 'document_original',
    ...overrides,
  };
}

function version(overrides = {}) {
  return {
    id: 'version-1',
    template_id: 'template-1',
    portfolio_id: 'portfolio-1',
    property_id: 'property-1',
    unit_id: null,
    direction: 'move_out',
    version: 2,
    state: 'draft',
    based_on_version_id: 'version-0',
    revision: 'revision-1',
    etag: '"template-etag-1"',
    created_at: '2026-10-02T08:00:00Z',
    published_at: null,
    steps: [templateStep()],
    actions: { edit_template: true, publish_template: true },
    ...overrides,
  };
}

function preparedSaveFactory() {
  return vi.fn(({ version: source, steps }) => {
    const payload = updateTemplateVersionCommand(source, steps, 'save-key');
    return {
      payload,
      send: vi.fn(async () => ({
        ...source,
        revision: 'revision-2',
        etag: '"template-etag-2"',
        steps: payload.steps.map((step, index) => ({
          ...step,
          id: source.steps[index]?.id || `server-${index}`,
        })),
      })),
    };
  });
}

describe('WorkflowTemplateDesigner', () => {
  it('exposes all four date anchors and changes responsibility from role to a concrete active user', async () => {
    const prepareSave = preparedSaveFactory();
    const userLoader = vi.fn(async () => ({
      items: [
        { id: 'user-tech', full_name: 'Technik Aktiv', role: 'techniker' },
        { id: 'user-owner', full_name: 'Verwaltung Aktiv', role: 'verwalter' },
      ],
      next_cursor: null,
      has_more: false,
      selected: null,
    }));

    render(<WorkflowTemplateDesigner
      version={version()}
      userLoader={userLoader}
      prepareSave={prepareSave}
      preparePublish={vi.fn()}
    />);

    const anchor = screen.getByLabelText('Terminanker');
    expect(within(anchor).getAllByRole('option')).toHaveLength(4);
    expect(within(anchor).getByRole('option', { name: 'Ende vorheriger Vertrag' })).toBeInTheDocument();
    expect(within(anchor).getByRole('option', { name: 'Beginn neuer Vertrag' })).toBeInTheDocument();
    expect(within(anchor).getByRole('option', { name: 'Auszugsübergabe' })).toBeInTheDocument();
    expect(within(anchor).getByRole('option', { name: 'Einzugsübergabe' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('radio', { name: 'Konkreter Benutzer' }));
    const active = await screen.findByRole('option', { name: /Technik Aktiv/ });
    fireEvent.click(active);
    fireEvent.click(screen.getByRole('button', { name: 'Entwurf speichern' }));

    await waitFor(() => expect(prepareSave).toHaveBeenCalledTimes(1));
    const saved = prepareSave.mock.calls[0][0].steps[0];
    expect(saved.assignee_user_id).toBe('user-tech');
    expect(saved.assignee_role).toBeNull();
  });

  it('prevents a cyclic dependency graph before any write command is prepared', () => {
    const prepareSave = preparedSaveFactory();
    const twoSteps = [
      templateStep({ id: 'step-a', stable_key: 'a', title: 'A', position: 0 }),
      templateStep({ id: 'step-b', stable_key: 'b', title: 'B', position: 1 }),
    ];
    render(<WorkflowTemplateDesigner
      version={version({ steps: twoSteps })}
      userLoader={async () => ({ items: [], next_cursor: null, has_more: false, selected: null })}
      prepareSave={prepareSave}
      preparePublish={vi.fn()}
    />);

    const dependencyGroups = screen.getAllByRole('group', { name: 'Abhängigkeiten' });
    fireEvent.click(within(dependencyGroups[0]).getByRole('checkbox', { name: 'B' }));
    fireEvent.click(within(dependencyGroups[1]).getByRole('checkbox', { name: 'A' }));
    fireEvent.click(screen.getByRole('button', { name: 'Entwurf speichern' }));

    expect(screen.getByRole('alert')).toHaveTextContent('Die Abhängigkeiten enthalten einen Zyklus.');
    expect(prepareSave).not.toHaveBeenCalled();
  });

  it('keeps an existing server stable key unchanged while the visible step title changes', async () => {
    const prepareSave = preparedSaveFactory();
    render(<WorkflowTemplateDesigner
      version={version({
        steps: [templateStep({ stable_key: 'published-handover-key', title: 'Alter Titel' })],
      })}
      userLoader={async () => ({ items: [], next_cursor: null, has_more: false, selected: null })}
      prepareSave={prepareSave}
      preparePublish={vi.fn()}
    />);

    expect(screen.queryByLabelText('Stabiler Schlüssel')).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Titel'), { target: { value: 'Neuer sichtbarer Titel' } });
    fireEvent.click(screen.getByRole('button', { name: 'Entwurf speichern' }));

    await waitFor(() => expect(prepareSave).toHaveBeenCalledTimes(1));
    expect(prepareSave.mock.calls[0][0].steps[0]).toMatchObject({
      stable_key: 'published-handover-key',
      title: 'Neuer sichtbarer Titel',
    });
  });

  it('projects server step ids out of update requests and then publishes the saved draft revision', async () => {
    const prepareSave = preparedSaveFactory();
    const publishSend = vi.fn(async source => ({
      ...source,
      state: 'published',
      revision: 'revision-3',
      etag: '"template-etag-3"',
      published_at: '2026-10-02T09:00:00Z',
      actions: { edit_template: false, publish_template: false },
    }));
    const preparePublish = vi.fn(({ version: source }) => ({
      payload: publishTemplateVersionCommand(source, 'publish-key'),
      send: () => publishSend(source),
    }));

    function Harness() {
      const [current, setCurrent] = useState(() => version({
        id: 'draft-version-2',
        steps: [templateStep({
          id: 'server-step-77',
          stable_key: 'stable-published-key',
          title: 'Vom Server geladener Schritt',
        })],
      }));
      return <WorkflowTemplateDesigner
        version={current}
        userLoader={async () => ({ items: [], next_cursor: null, has_more: false, selected: null })}
        prepareSave={prepareSave}
        preparePublish={preparePublish}
        onChanged={setCurrent}
      />;
    }

    render(<Harness />);

    fireEvent.change(screen.getByLabelText('Titel'), { target: { value: 'Geändert' } });
    fireEvent.click(screen.getByRole('button', { name: 'Entwurf speichern' }));
    await waitFor(() => expect(prepareSave).toHaveBeenCalledTimes(1));

    const request = prepareSave.mock.results[0].value.payload;
    expect(request.steps).toEqual([{
      stable_key: 'stable-published-key',
      position: 0,
      title: 'Geändert',
      description: null,
      default_requirement: 'required',
      anchor: 'move_out_handover',
      offset_days: 0,
      assignee_user_id: null,
      assignee_role: 'techniker',
      depends_on_step_keys: [],
      evidence_requirement: 'document_original',
    }]);
    expect(request.steps[0]).not.toHaveProperty('id');

    await waitFor(() => expect(screen.getByRole('button', { name: 'Version veröffentlichen' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Version veröffentlichen' }));
    await waitFor(() => expect(preparePublish).toHaveBeenCalledTimes(1));
    expect(preparePublish.mock.results[0].value.payload).toEqual({
      idempotency_key: 'publish-key',
      expected_revision: 'revision-2',
    });
    await waitFor(() => expect(publishSend).toHaveBeenCalledTimes(1));
    expect(await screen.findByText('Veröffentlicht')).toBeInTheDocument();
  });

  it('uses server actions instead of inferring edit rights from a role', () => {
    render(<WorkflowTemplateDesigner
      version={version({ actions: { edit_template: false, publish_template: false } })}
      userLoader={async () => ({ items: [], next_cursor: null, has_more: false, selected: null })}
    />);

    expect(screen.getByText('Diese Version ist nicht bearbeitbar.')).toBeInTheDocument();
    expect(screen.getByLabelText('Titel')).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Entwurf speichern' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Version veröffentlichen' })).not.toBeInTheDocument();
  });
});
