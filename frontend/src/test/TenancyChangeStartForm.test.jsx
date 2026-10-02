import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import TenancyChangeStartForm from '../features/tenancyWorkflows/TenancyChangeStartForm';
import { startTenancyChangeCommand } from '../features/tenancyWorkflows/tenancyWorkflowModel';

const oldContract = {
  id: 'old-contract',
  contract_number: 'OLD-1',
  property_id: 'property-1',
  unit_id: 'unit-1',
  start_date: '2020-01-01',
  end_date: '2026-10-31',
};
const newContract = {
  id: 'new-contract',
  contract_number: 'NEW-1',
  property_id: 'property-1',
  unit_id: 'unit-1',
  start_date: '2026-11-01',
  end_date: null,
};
const outTemplate = {
  id: 'out-version',
  version: 4,
  property_id: 'property-1',
  unit_id: null,
  direction: 'move_out',
  state: 'published',
};
const inTemplate = {
  id: 'in-version',
  version: 2,
  property_id: 'property-1',
  unit_id: 'unit-1',
  direction: 'move_in',
  state: 'published',
};

function createdChange() {
  return {
    id: 'change-1',
    portfolio_id: 'portfolio-1',
    property_id: 'property-1',
    unit_id: 'unit-1',
    previous_contract_id: 'old-contract',
    next_contract_id: 'new-contract',
    mode: 'turnover',
    move_out_handover_date: '2026-10-28',
    move_in_handover_date: '2026-11-03',
    move_out_template_version_id: 'out-version',
    move_in_template_version_id: 'in-version',
    state: 'active',
    revision: 'change-rev-1',
    etag: '"change-etag"',
    created_by: 'manager-1',
    created_at: '2026-10-02T10:00:00Z',
    updated_at: '2026-10-02T10:00:00Z',
    snapshot_sha256: 'd'.repeat(64),
    steps: [],
    actions: { edit_change: true, reanchor: true, complete_change: true },
  };
}

describe('TenancyChangeStartForm', () => {
  function mount(overrides = {}) {
    const loadContracts = vi.fn(async () => ({
      items: [oldContract, newContract],
      next_cursor: null,
      has_more: false,
      selected: null,
    }));
    const loadTemplates = vi.fn(async ({ direction }) => ({
      items: [direction === 'move_out' ? outTemplate : inTemplate],
      next_cursor: null,
      has_more: false,
    }));
    const onPreview = vi.fn(async payload => ({
      preview_hash: 'a'.repeat(64),
      anchors: {
        previous_contract_end: oldContract.end_date,
        next_contract_start: newContract.start_date,
        move_out_handover: payload.move_out_handover_date,
        move_in_handover: payload.move_in_handover_date,
      },
      affected_steps: [{ id: 's1', title: 'Termin abstimmen' }],
      source_etags: { previous_contract: '"old"', next_contract: '"new"' },
      conflicts: [],
    }));
    const onCreated = vi.fn();
    const prepareCreate = vi.fn(({ form, preview }) => ({
      payload: startTenancyChangeCommand(form, preview, 'create-key'),
      send: vi.fn(async () => createdChange()),
    }));
    render(<TenancyChangeStartForm
      propertyId="property-1"
      unitId="unit-1"
      loadContracts={loadContracts}
      loadTemplates={loadTemplates}
      onPreview={onPreview}
      prepareCreate={prepareCreate}
      onCreated={onCreated}
      {...overrides}
    />);
    return { loadContracts, loadTemplates, onPreview, prepareCreate, onCreated };
  }

  async function chooseReferences() {
    const previous = await screen.findByRole('listbox', { name: /Vorheriger Vertrag/ });
    const old = within(previous).getByRole('option', { name: /OLD-1/ });
    expect(within(previous).queryByRole('option', { name: /FOREIGN/ })).not.toBeInTheDocument();
    fireEvent.click(old);

    const next = screen.getByRole('listbox', { name: /Neuer Vertrag/ });
    fireEvent.click(within(next).getByRole('option', { name: /NEW-1/ }));

    const outTemplate = await screen.findByRole('listbox', { name: /Auszugsvorlage/ });
    fireEvent.click(within(outTemplate).getByRole('option', { name: /Version 4/ }));
    const inTemplate = await screen.findByRole('listbox', { name: /Einzugsvorlage/ });
    fireEvent.click(within(inTemplate).getByRole('option', { name: /Version 2/ }));
  }

  it('keeps contract dates and both explicit handover dates separate through preview and create', async () => {
    const { onPreview, prepareCreate, onCreated } = mount();
    await chooseReferences();

    fireEvent.change(screen.getByLabelText('Auszugsübergabe'), { target: { value: '2026-10-28' } });
    fireEvent.change(screen.getByLabelText('Einzugsübergabe'), { target: { value: '2026-11-03' } });
    fireEvent.click(screen.getByRole('button', { name: 'Vorschau erstellen' }));

    expect(await screen.findByText('Vorschau ist bereit')).toBeInTheDocument();
    const technical = screen.getByText('Technische Details').closest('details');
    expect(technical).not.toHaveAttribute('open');
    expect(onPreview).toHaveBeenCalledWith(expect.objectContaining({
      previous_contract_id: 'old-contract',
      next_contract_id: 'new-contract',
      move_out_handover_date: '2026-10-28',
      move_in_handover_date: '2026-11-03',
      move_out_template_version_id: 'out-version',
      move_in_template_version_id: 'in-version',
    }), expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(screen.getAllByText('31.10.2026').length).toBeGreaterThan(0);
    expect(screen.getAllByText('01.11.2026').length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole('button', { name: 'Wechselakte starten' }));
    await waitFor(() => expect(prepareCreate).toHaveBeenCalledTimes(1));
    expect(prepareCreate.mock.calls[0][0].preview.preview_hash).toBe('a'.repeat(64));
    expect(prepareCreate.mock.results[0].value.payload).toMatchObject({
      idempotency_key: 'create-key',
      expected_revision: 'new',
      preview_hash: 'a'.repeat(64),
      source_etags: { previous_contract: '"old"', next_contract: '"new"' },
    });
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ id: 'change-1' })));
    expect(screen.queryByText('Vorschau ist bereit')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Wechselakte starten' })).not.toBeInTheDocument();
  });

  it('keeps the prepared preview through an unknown reply and clears it only after exact retry succeeds', async () => {
    const networkError = Object.assign(new Error('response lost'), {
      isNetwork: true,
      code: 'NETWORK_ERROR',
    });
    const send = vi.fn()
      .mockRejectedValueOnce(networkError)
      .mockResolvedValueOnce(createdChange());
    const prepareCreate = vi.fn(({ form, preview }) => ({
      payload: startTenancyChangeCommand(form, preview, 'lost-reply-key'),
      send,
    }));
    const { onCreated } = mount({ prepareCreate });
    await chooseReferences();
    fireEvent.click(screen.getByRole('button', { name: 'Vorschau erstellen' }));
    expect(await screen.findByText('Vorschau ist bereit')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Wechselakte starten' }));
    expect(await screen.findByText('Verbindung unterbrochen')).toBeInTheDocument();
    expect(screen.getByText(/dieselbe vorbereitete Aktion unverändert/)).toBeInTheDocument();
    expect(screen.getByText('Vorschau ist bereit')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Wechselakte starten' })).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: 'Unverändert erneut senden' }));
    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
    expect(send).toHaveBeenCalledTimes(2);
    expect(send.mock.calls[1][0]).toBe(send.mock.calls[0][0]);
    expect(screen.queryByText('Vorschau ist bereit')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Wechselakte starten' })).not.toBeInTheDocument();
  });

  it('invalidates a preview immediately when an anchor input changes', async () => {
    const { prepareCreate } = mount();
    await chooseReferences();
    fireEvent.click(screen.getByRole('button', { name: 'Vorschau erstellen' }));
    expect(await screen.findByText('Vorschau ist bereit')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Auszugsübergabe'), { target: { value: '2026-10-29' } });
    expect(screen.queryByText('Vorschau ist bereit')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Wechselakte starten' })).not.toBeInTheDocument();
    expect(prepareCreate).not.toHaveBeenCalled();
  });
});
