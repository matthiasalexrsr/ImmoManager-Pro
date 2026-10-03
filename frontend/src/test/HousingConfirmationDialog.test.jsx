import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const authState = vi.hoisted(() => ({
  user: {
    id: 'manager-1',
    role: 'verwalter',
    is_active: true,
    write_permissions: ['documents', 'rental'],
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
  source_etags: {
    portfolio: '"p"', contract: '"c"', property: '"pr"', unit: '"u"', tenant: '"t"', wizard_revision: null,
  },
};

const historicalData = {
  housing_provider_name: 'Wohnungsgeber GmbH',
  housing_provider_address: 'Weg 2\n12345 Berlin',
  owner_same_as_provider: false,
  owner_name: 'Eigentümerin Beispiel',
  move_in_date: '2026-10-15',
  issue_date: '2026-10-16',
  apartment_address: 'Parkweg 1\n12345 Berlin',
  apartment_label: '2. OG links',
  issuer_name: 'Beauftragte Person',
  issuer_role: 'authorized_person',
  residents: ['Alex Beispiel'],
};
const historicalRecord = {
  id: 'document-old',
  document_id: 'document-old',
  version_id: 'version-old',
  contract_id: 'contract-1',
  issue_date: '2026-10-16',
  created_at: '2026-10-16T12:00:00+00:00',
  data: historicalData,
  correction_of: null,
};

function service(overrides = {}) {
  return {
    loadSource: vi.fn(async () => source),
    listHistory: vi.fn(async () => ({ items: [], next_cursor: null })),
    preview: vi.fn(async ({ data }) => ({
      review_hash: 'a'.repeat(64),
      person_count: data.residents.length,
      warnings: [],
    })),
    ...overrides,
  };
}

async function fillRequiredHousingForm() {
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
}

describe('HousingConfirmationDialog adapter shell', () => {
  beforeEach(() => {
    confirmMock.mockClear();
    authState.user = {
      id: 'manager-1',
      role: 'verwalter',
      is_active: true,
      write_permissions: ['documents', 'rental'],
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

  it('keeps preview while collecting all three release confirmations and forwards them to SaveRequest preparation', async () => {
    const preparePublish = vi.fn(({ confirmations }) => ({
      payload: {
        idempotency_key: 'housing-key',
        review_hash: 'a'.repeat(64),
        ...confirmations,
      },
      send: vi.fn(async () => ({
        id: 'document-1',
        document_id: 'document-1',
        version_id: 'version-1',
        contract_id: 'contract-1',
        issue_date: '2026-10-16',
        data: {},
      })),
    }));
    const api = service({ preparePublish });
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

    fireEvent.click(screen.getByLabelText(/eingetragenen Personen tatsächlich/));
    fireEvent.click(screen.getByLabelText(/ausstellende Person zur Ausstellung/));
    fireEvent.click(screen.getByLabelText(/angegebene Einzugsdatum der tatsächliche Einzug/));
    expect(screen.getByText('Vorläufige Vorschau geprüft')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Freigeben und Original speichern' }));
    await waitFor(() => expect(preparePublish).toHaveBeenCalledTimes(1));
    expect(preparePublish.mock.calls[0][0].confirmations).toEqual({
      confirmed_actual_move_in: true,
      confirmed_authority: true,
      confirmed_residents: true,
    });
  });

  it('keeps entered data and requires an explicit source reload after preview 412', async () => {
    const stale = Object.assign(new Error('stale source'), { statusCode: 412 });
    const api = service({ preview: vi.fn(async () => { throw stale; }) });
    render(<HousingConfirmationDialog contractId="contract-1" service={api} onClose={vi.fn()} />);

    await fillRequiredHousingForm();
    fireEvent.click(screen.getByRole('button', { name: 'Vorschau prüfen' }));

    expect(await screen.findByText('Quelldaten haben sich geändert')).toBeInTheDocument();
    expect(screen.getByLabelText(/^Tatsächlicher Einzug/)).toHaveValue('2026-10-15');
    fireEvent.click(screen.getByRole('button', { name: 'Aktuelle Quellen neu prüfen' }));
    await waitFor(() => expect(api.loadSource).toHaveBeenCalledTimes(2));
    expect(screen.getByLabelText(/^Tatsächlicher Einzug/)).toHaveValue('2026-10-15');
  });

  it('opens a saved original and previews a correction with exact document/version binding', async () => {
    const openOriginal = vi.fn(async () => {});
    const api = service({
      listHistory: vi.fn(async () => ({ items: [historicalRecord], next_cursor: null })),
      openOriginal,
    });
    render(<HousingConfirmationDialog contractId="contract-1" service={api} onClose={vi.fn()} />);

    await screen.findByText('16.10.2026');
    fireEvent.click(screen.getByRole('button', { name: 'PDF öffnen' }));
    await waitFor(() => expect(openOriginal).toHaveBeenCalledWith(
      historicalRecord,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    ));

    fireEvent.click(screen.getByRole('button', { name: 'Korrektur erstellen' }));
    expect(screen.getByText('Korrektur wird vorbereitet')).toBeInTheDocument();
    expect(screen.getByLabelText(/^Tatsächlicher Einzug/)).toHaveValue('2026-10-15');
    fireEvent.click(screen.getByRole('button', { name: 'Vorschau prüfen' }));
    await waitFor(() => expect(api.preview).toHaveBeenCalledWith(
      expect.objectContaining({
        correctionOf: { document_id: 'document-old', version_id: 'version-old' },
        data: expect.objectContaining({ move_in_date: '2026-10-15' }),
      }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    ));
  });

  it('warns before closing dirty personal data and keeps the dialog when declined', async () => {
    confirmMock.mockResolvedValueOnce(false);
    const onClose = vi.fn();
    render(<HousingConfirmationDialog contractId="contract-1" service={service()} onClose={onClose} />);
    await screen.findByText('MV-2026-1 · Haus am Park · Wohnung 2. OG links');

    fireEvent.change(screen.getByLabelText('Name des Wohnungsgebers'), { target: { value: 'Privater Entwurf' } });
    fireEvent.click(screen.getAllByRole('button', { name: 'Schließen' })[0]);

    await waitFor(() => expect(confirmMock).toHaveBeenCalledWith(
      'Ungespeicherte Angaben oder eine ungeklärte Freigabe würden verworfen. Wirklich schließen?',
    ));
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Name des Wohnungsgebers')).toHaveValue('Privater Entwurf');
  });

  it('hides prior private content on the first render of a changed contract/actor/role/portfolio binding', async () => {
    const loadSource = vi.fn()
      .mockResolvedValueOnce(source)
      .mockImplementationOnce(() => new Promise(() => {}));
    const api = service({ loadSource });
    const view = render(
      <HousingConfirmationDialog contractId="contract-1" service={api} onClose={vi.fn()} />,
    );
    expect(await screen.findByText('MV-2026-1 · Haus am Park · Wohnung 2. OG links')).toBeInTheDocument();

    authState.user = {
      id: 'other-user',
      role: 'readonly',
      is_active: true,
      write_permissions: [],
      portfolio_access: 'selected',
      portfolio_ids: ['portfolio-2'],
    };
    view.rerender(
      <HousingConfirmationDialog contractId="contract-2" service={api} onClose={vi.fn()} />,
    );

    expect(screen.queryByText('MV-2026-1 · Haus am Park · Wohnung 2. OG links')).not.toBeInTheDocument();
    expect(screen.getByText('Lade aktuelle Vertragsdaten …')).toBeInTheDocument();
    await waitFor(() => expect(loadSource).toHaveBeenCalledTimes(2));
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
