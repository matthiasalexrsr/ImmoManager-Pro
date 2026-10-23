import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { detailFixture } from './handoverFixtures';

const context = vi.hoisted(() => ({
  store: { invalidateRelated: () => {} },
  entities: {
    units: [{ id: 'u-1', label: 'WE 3' }],
    contracts: [{ id: 'c-1', contract_number: 'V-1' }],
  },
}));
vi.mock('../contexts/DataStoreContext', () => ({
  useEntities: key => ({ items: context.entities[key] || [], loading: false, error: null }),
  useDataStore: () => context.store,
}));
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'u', role: 'verwalter' }, write: null }),
  useCanWrite: () => true,
}));
vi.mock('../components/Toast', () => ({ useToast: () => ({ error: vi.fn(), success: vi.fn() }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => async () => true }));
vi.mock('../components/PdfPreview', () => ({ default: () => <div /> }));
vi.mock('../utils/uploadAccess', () => ({ prepareUploadAccess: vi.fn(async () => {}), isOwnUploadUrl: () => true }));

import HandoverProtocols from '../pages/HandoverProtocols';

function service() {
  return {
    list: vi.fn(async () => [
      { id: 'p-1', contract_id: 'c-1', unit_id: 'u-1', protocol_type: 'move_out', protocol_date: '2026-06-30',
        status: 'finalized', finalized_at: '2026-07-01T09:00:00', correction_of_id: null },
      { id: 'p-2', contract_id: 'c-1', unit_id: 'u-1', protocol_type: 'move_out', protocol_date: '2026-06-30',
        status: 'draft', finalized_at: null, correction_of_id: 'p-1' },
    ]),
    create: vi.fn(async () => detailFixture({ protocol: { ...detailFixture().protocol, id: 'p-3' } })),
    load: vi.fn(async id => detailFixture({ protocol: { ...detailFixture().protocol, id } })),
    remove: vi.fn(async () => null),
  };
}

describe('HandoverProtocols page', () => {
  it('lists every protocol with its kind and state and opens one in the editor', async () => {
    const api = service();
    render(<HandoverProtocols service={api} />);
    expect(await screen.findByText('Korrektur (Entwurf)')).toBeInTheDocument();
    expect(screen.getByText('Abgeschlossen')).toBeInTheDocument();
    expect(screen.getAllByText('Auszug')).toHaveLength(2);
    fireEvent.click(screen.getByText('Korrektur (Entwurf)'));
    await waitFor(() => expect(api.load).toHaveBeenCalledWith('p-2', expect.anything()));
    expect(await screen.findByRole('dialog', { name: /Übergabeprotokoll – Auszug/ })).toBeInTheDocument();
  });

  it('creates a prefilled protocol for the chosen contract and opens it', async () => {
    const api = service();
    render(<HandoverProtocols service={api} />);
    await screen.findByText('Abgeschlossen');
    fireEvent.click(screen.getByRole('button', { name: /ui\.buttons\.new/ }));
    const modal = await screen.findByRole('dialog', { name: 'Neues Übergabeprotokoll' });
    fireEvent.change(within(modal).getByLabelText(/Vertrag/), { target: { value: 'c-1' } });
    fireEvent.change(within(modal).getByLabelText(/Art/), { target: { value: 'move_in' } });
    fireEvent.click(within(modal).getByRole('button', { name: 'ui.buttons.save' }));
    await waitFor(() => expect(api.create).toHaveBeenCalledWith('c-1', 'move_in', null));
    await waitFor(() => expect(api.load).toHaveBeenCalledWith('p-3', expect.anything()));
  });
});
