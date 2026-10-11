import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { detailFixture } from './handoverFixtures';

const authState = vi.hoisted(() => ({ user: null, write: null }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => authState }));
vi.mock('../components/PdfPreview', () => ({ default: () => <div data-testid="pdf" /> }));
vi.mock('../utils/uploadAccess', () => ({ prepareUploadAccess: vi.fn(async () => {}), isOwnUploadUrl: () => true }));
vi.mock('../features/housingConfirmation/HousingConfirmationDialog', () => ({
  default: ({ contractId }) => <div role="dialog" aria-label="WGB">WGB {contractId}</div>,
}));

import HandoverProtocolsDialog from '../features/handoverProtocol/HandoverProtocolsDialog';

const source = {
  contract_id: 'c-1',
  source: { contract: { id: 'c-1', contract_number: 'V-1' }, property: { name: 'Bautzner Straße 61' },
    unit: { label: 'WE 3' } },
  protocols: [
    { id: 'p-new', protocol_type: 'move_out', protocol_date: '2026-06-30', status: 'finalized',
      finalized_at: '2026-07-02T09:00:00', correction_of_id: 'p-old', document_id: 'd-2' },
    { id: 'p-old', protocol_type: 'move_out', protocol_date: '2026-06-30', status: 'finalized',
      finalized_at: '2026-07-01T09:00:00', correction_of_id: null, document_id: 'd-1' },
    { id: 'p-in', protocol_type: 'move_in', protocol_date: '2024-01-01', status: 'draft', finalized_at: null,
      correction_of_id: null, document_id: null },
  ],
  related: {
    previous_contract: null,
    next_contract: { id: 'c-2', contract_number: 'V-2', start_date: '2026-07-01', end_date: null, status: 'active' },
    housing_confirmation_contract_id: 'c-1', templates: [],
  },
  suggestion: {}, meters: [],
};

function service() {
  return {
    source: vi.fn(async () => source),
    create: vi.fn(async (contractId, protocolType) => detailFixture({
      protocol: { ...detailFixture().protocol, id: `${contractId}-${protocolType}`, protocol_type: protocolType } })),
    load: vi.fn(async id => detailFixture({ protocol: { ...detailFixture().protocol, id } })),
  };
}

describe('HandoverProtocolsDialog', () => {
  beforeEach(() => {
    authState.user = { id: 'manager-1', role: 'verwalter' };
    authState.write = null;
  });

  it('lists the contract protocols and names the corrected one', async () => {
    render(<HandoverProtocolsDialog contractId="c-1" service={service()} onClose={vi.fn()} />);
    await screen.findByText('V-1 · Bautzner Straße 61 · WE 3');
    expect(screen.getAllByText('Abgeschlossen')).toHaveLength(1);
    expect(screen.getByText('Durch Korrektur ersetzt')).toBeInTheDocument();
    expect(screen.getByText('Entwurf')).toBeInTheDocument();
    expect(screen.getByText('Briefvorlagen für den Mieterwechsel sind nicht hinterlegt.')).toBeInTheDocument();
  });

  it('starts the next tenant\'s move-in from the tenant change and opens the editor', async () => {
    const api = service();
    const changed = vi.fn();
    render(<HandoverProtocolsDialog contractId="c-1" service={api} onClose={vi.fn()} onChanged={changed} />);
    expect(await screen.findByText(/Nachmieter: Vertrag V-2/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Einzug des Nachmieters' }));
    await waitFor(() => expect(api.create).toHaveBeenCalledWith('c-2', 'move_in'));
    await waitFor(() => expect(api.load).toHaveBeenCalledWith('c-2-move_in', expect.anything()));
    expect(changed).toHaveBeenCalled();
    fireEvent.click(screen.getAllByRole('button', { name: 'Schließen' })[0]);
  });

  it('records a move-out for this contract and offers the Wohnungsgeberbestätigung', async () => {
    const api = service();
    render(<HandoverProtocolsDialog contractId="c-1" service={api} onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Auszug protokollieren' }));
    await waitFor(() => expect(api.create).toHaveBeenCalledWith('c-1', 'move_out'));
    await screen.findAllByText('V-1 · Bautzner Straße 61 · WE 3');
  });

  it('opens the Wohnungsgeberbestätigung of the contract', async () => {
    render(<HandoverProtocolsDialog contractId="c-1" service={service()} onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Wohnungsgeberbestätigung' }));
    expect(await screen.findByText('WGB c-1')).toBeInTheDocument();
  });

  it('shows no create buttons to a read-only role', async () => {
    authState.write = [];
    render(<HandoverProtocolsDialog contractId="c-1" service={service()} onClose={vi.fn()} />);
    await screen.findByText('V-1 · Bautzner Straße 61 · WE 3');
    expect(screen.queryByRole('button', { name: 'Einzug protokollieren' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Einzug des Nachmieters' })).not.toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /^Öffnen:/ })).toHaveLength(3);
  });
});
