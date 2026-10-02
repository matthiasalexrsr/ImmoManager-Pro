import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const authState = vi.hoisted(() => ({
  user: {
    id: 'manager-1',
    role: 'verwalter',
    is_active: true,
    write_permissions: ['documents'],
    portfolio_access: 'selected',
    portfolio_ids: ['portfolio-1'],
  },
}));
const confirmMock = vi.hoisted(() => vi.fn(async () => true));

vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ user: authState.user }),
}));
vi.mock('../components/ConfirmDialog', () => ({
  useConfirm: () => confirmMock,
}));

import HousingConfirmationDialog from '../features/housingConfirmation/HousingConfirmationDialog';

const source = {
  contract_id: 'contract-1',
  contract_number: 'MV-2026-1',
  property_label: 'Haus am Park',
  unit_label: 'Wohnung 2. OG links',
  suggestions: {
    dwelling_address: 'Parkweg 1\n12345 Berlin',
    dwelling_label: '2. OG links',
    main_tenant_name: 'Hauptmieter Beispiel',
    owner_name: 'Eigentümerin Beispiel',
  },
  reference_dates: {
    contract_start_date: '2026-10-01',
    handover_date: '2026-10-12',
  },
  actions: { preview: true, publish: true },
};

function service(overrides = {}) {
  return {
    loadSource: vi.fn(async () => source),
    listHistory: vi.fn(async () => ({ items: [], next_cursor: null })),
    preview: vi.fn(async ({ data }) => ({
      review_hash: 'a'.repeat(64),
      person_count: data.occupant_names.length,
      warnings: [],
    })),
    ...overrides,
  };
}

describe('HousingConfirmationDialog adapter shell', () => {
  beforeEach(() => {
    confirmMock.mockClear();
    authState.user = {
      id: 'manager-1',
      role: 'verwalter',
      is_active: true,
      write_permissions: ['documents'],
      portfolio_access: 'selected',
      portfolio_ids: ['portfolio-1'],
    };
  });

  it('shows suggestions without guessing tenant or move-in data and adds the main tenant only explicitly', async () => {
    render(<HousingConfirmationDialog contractId="contract-1" service={service()} onClose={vi.fn()} />);

    expect(await screen.findByText('MV-2026-1 · Haus am Park · Wohnung 2. OG links')).toBeInTheDocument();
    expect(screen.getByLabelText(/^Tatsächlicher Einzug/)).toHaveValue('');
    expect(screen.getByLabelText('Vollständiger Name 1')).toHaveValue('');

    const suggestion = screen.getByText('Hauptmieter Beispiel').closest('.housing-confirmation__suggestion');
    fireEvent.click(within(suggestion).getByRole('button', { name: 'Vorschlag hinzufügen' }));

    expect(screen.getByLabelText('Vollständiger Name 1')).toHaveValue('');
    expect(screen.getByLabelText('Vollständiger Name 2')).toHaveValue('Hauptmieter Beispiel');
  });

  it('invalidates a preview as soon as a reviewed field changes', async () => {
    const api = service();
    render(<HousingConfirmationDialog contractId="contract-1" service={api} onClose={vi.fn()} />);

    await screen.findByText('MV-2026-1 · Haus am Park · Wohnung 2. OG links');
    fireEvent.click(screen.getByText('Adressvorschlag').closest('.housing-confirmation__suggestion')
      .querySelector('button'));
    fireEvent.change(screen.getByLabelText('Name des Wohnungsgebers'), { target: { value: 'WG GmbH' } });
    fireEvent.change(screen.getByLabelText('Anschrift des Wohnungsgebers'), { target: { value: 'Weg 2' } });
    fireEvent.change(screen.getByLabelText('Eigentumsverhältnis'), { target: { value: 'same' } });
    fireEvent.change(screen.getByLabelText(/^Tatsächlicher Einzug/), { target: { value: '2026-10-15' } });
    fireEvent.change(screen.getByLabelText('Ausstellungsdatum'), { target: { value: '2026-10-16' } });
    fireEvent.change(screen.getByLabelText('Ausstellende Person'), { target: { value: 'Beauftragte Person' } });
    fireEvent.change(screen.getByLabelText('Rolle der ausstellenden Person'), { target: { value: 'authorized_person' } });
    fireEvent.change(screen.getByLabelText('Vollständiger Name 1'), { target: { value: 'Alex Beispiel' } });

    fireEvent.click(screen.getByRole('button', { name: 'Vorschau prüfen' }));
    expect(await screen.findByText('Vorläufige Vorschau geprüft')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/^Tatsächlicher Einzug/), { target: { value: '2026-10-17' } });
    expect(screen.queryByText('Vorläufige Vorschau geprüft')).not.toBeInTheDocument();
    expect(screen.getByText('Die Vorschau wurde wegen einer Änderung verworfen.')).toBeInTheDocument();
  });

  it('forgets private display on a fresh 403 source response', async () => {
    const forbidden = Object.assign(new Error('forbidden'), { statusCode: 403 });
    const api = service({ loadSource: vi.fn(async () => { throw forbidden; }) });
    render(<HousingConfirmationDialog contractId="contract-1" service={api} onClose={vi.fn()} />);

    expect(await screen.findByText('Die Wohnungsgeberbestätigung ist in diesem Zugriff nicht verfügbar.'))
      .toBeInTheDocument();
    expect(screen.queryByText('Hauptmieter Beispiel')).not.toBeInTheDocument();
    await waitFor(() => expect(api.listHistory).toHaveBeenCalled());
  });
});
