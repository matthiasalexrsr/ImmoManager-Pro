import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const authState = vi.hoisted(() => ({ user: null, write: null }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => authState }));
vi.mock('../components/PdfPreview', () => ({ default: ({ url, title }) => <div data-testid="pdf">{title}|{url}</div> }));

import HousingConfirmationDialog from '../features/housingConfirmation/HousingConfirmationDialog';

const source = {
  contract_id: 'contract-1', contract_number: 'V-2026-1', property_label: 'Bautzner Straße 61', unit_label: 'WE 3',
  suggestions: {
    dwelling_address: 'Bautzner Straße 61\n01099 Dresden', dwelling_label: 'WE 3', main_tenant_name: 'Mia Muster',
    housing_provider_name: 'Linda Reiser', housing_provider_address: null, owner_name: 'Linda Reiser',
  },
  reference_dates: { contract_start_date: '2024-01-01' },
  source_etags: { portfolio: '"p"', contract: '"c"', property: '"pr"', unit: '"u"', tenant: '"t"', wizard_revision: null },
};
const stored = {
  id: 'doc-1', document_id: 'doc-1', version_id: 'ver-1', contract_id: 'contract-1', pdf_sha256: 'b'.repeat(64),
  issue_date: '2026-10-07', created_at: '2026-10-07T10:00:00+00:00', correction_of: null,
  file_url: '/uploads/housing-confirmations/doc-1.pdf',
  data: {
    housing_provider_name: 'Linda Reiser', housing_provider_address: 'Prießnitzstraße 4', owner_same_as_provider: true,
    owner_name: null, move_in_date: '2026-02-03', issue_date: '2026-10-07', apartment_address: 'Bautzner Straße 61',
    apartment_label: 'WE 3', issuer_name: 'Linda Reiser', issuer_role: 'housing_provider', residents: ['Mia Muster'],
  },
};

function service(overrides = {}) {
  return {
    loadSource: vi.fn(async () => source),
    listHistory: vi.fn(async () => ({ items: [], next_cursor: null })),
    preview: vi.fn(async ({ data }) => ({ review_hash: 'a'.repeat(64), pdf_sha256: 'c'.repeat(64), size_bytes: 900,
      person_count: data.residents.length })),
    previewPdfUrl: vi.fn(async () => 'blob:preview'),
    preparePublish: vi.fn(input => ({ payload: { ...input, idempotency_key: 'k-1' }, send: vi.fn(async () => stored) })),
    downloadOriginal: vi.fn(async () => {}),
    ...overrides,
  };
}

async function fillForm() {
  await screen.findByText('V-2026-1 · Bautzner Straße 61 · WE 3');
  const address = screen.getByText('Adressvorschlag').closest('.housing-confirmation__suggestion');
  fireEvent.click(within(address).getByRole('button'));
  fireEvent.change(screen.getByLabelText('Name des Wohnungsgebers'), { target: { value: 'Linda Reiser' } });
  fireEvent.change(screen.getByLabelText('Anschrift des Wohnungsgebers'), { target: { value: 'Prießnitzstraße 4' } });
  fireEvent.change(screen.getByLabelText('Eigentumsverhältnis'), { target: { value: 'same' } });
  fireEvent.change(screen.getByLabelText(/^Tatsächlicher Einzug/), { target: { value: '2026-02-03' } });
  fireEvent.change(screen.getByLabelText('Ausstellungsdatum'), { target: { value: '2026-10-07' } });
  fireEvent.change(screen.getByLabelText('Ausstellende Person'), { target: { value: 'Linda Reiser' } });
  fireEvent.change(screen.getByLabelText('Rolle der ausstellenden Person'), { target: { value: 'housing_provider' } });
  fireEvent.change(screen.getByLabelText('Vollständiger Name 1'), { target: { value: 'Mia Muster' } });
}

function confirmAll() {
  for (const text of [/tatsächlich in die Wohnung einziehen/, /zur Ausstellung dieser Bestätigung befugt/, /tatsächliche Einzug ist/]) {
    fireEvent.click(screen.getByLabelText(text));
  }
}

describe('HousingConfirmationDialog', () => {
  beforeEach(() => {
    authState.user = { id: 'manager-1', role: 'verwalter' };
    authState.write = null;
  });

  it('suggests but fills in neither the move-in date nor the residents on its own', async () => {
    render(<HousingConfirmationDialog contractId="contract-1" service={service()} onClose={vi.fn()} />);

    await screen.findByText('V-2026-1 · Bautzner Straße 61 · WE 3');
    expect(screen.getByLabelText(/^Tatsächlicher Einzug/)).toHaveValue('');
    expect(screen.getByLabelText('Vollständiger Name 1')).toHaveValue('');
    const tenant = screen.getByText('Hauptmieter als Vorschlag').closest('.housing-confirmation__suggestion');
    fireEvent.click(within(tenant).getByRole('button', { name: 'Vorschlag hinzufügen' }));
    expect(screen.getByLabelText('Vollständiger Name 2')).toHaveValue('Mia Muster');
  });

  it('reviews, shows the PDF, and publishes only with all three confirmations', async () => {
    const api = service();
    const onPublished = vi.fn();
    render(<HousingConfirmationDialog contractId="contract-1" service={api} onClose={vi.fn()} onPublished={onPublished} />);
    await fillForm();

    fireEvent.click(screen.getByRole('button', { name: 'Vorschau prüfen' }));
    expect(await screen.findByText('Vorläufige Vorschau geprüft')).toBeInTheDocument();
    expect(api.preview.mock.calls[0][0].data).toMatchObject({ move_in_date: '2026-02-03', residents: ['Mia Muster'],
      owner_same_as_provider: true, owner_name: null });

    fireEvent.click(screen.getByRole('button', { name: /PDF-Vorschau öffnen/ }));
    expect(await screen.findByTestId('pdf')).toHaveTextContent('blob:preview');
    fireEvent.click(screen.getByRole('button', { name: /Zurück zum Formular/ }));

    fireEvent.click(screen.getByRole('button', { name: 'Freigeben und Original speichern' }));
    expect(screen.getByText('Bitte alle erforderlichen Angaben prüfen.')).toBeInTheDocument();
    expect(api.preparePublish).not.toHaveBeenCalled();

    confirmAll();
    fireEvent.click(screen.getByRole('button', { name: 'Freigeben und Original speichern' }));
    expect(await screen.findByText(/als unveränderliches Original gespeichert/)).toBeInTheDocument();
    expect(api.preparePublish.mock.calls[0][0].preview.review_hash).toBe('a'.repeat(64));
    expect(screen.getByRole('button', { name: 'Korrektur erstellen' })).toBeInTheDocument();
    expect(onPublished).toHaveBeenCalledWith(stored);   // document lists and counts get refreshed
  });

  it('a changed input discards the reviewed preview', async () => {
    render(<HousingConfirmationDialog contractId="contract-1" service={service()} onClose={vi.fn()} />);
    await fillForm();
    fireEvent.click(screen.getByRole('button', { name: 'Vorschau prüfen' }));
    await screen.findByText('Vorläufige Vorschau geprüft');

    fireEvent.change(screen.getByLabelText(/^Tatsächlicher Einzug/), { target: { value: '2026-02-04' } });

    expect(screen.queryByText('Vorläufige Vorschau geprüft')).toBeNull();
    expect(screen.getByText('Die Vorschau wurde wegen einer Änderung verworfen.')).toBeInTheDocument();
  });

  it('keeps the exact release for a retry when the answer is lost', async () => {
    const lost = Object.assign(new Error('Verbindung'), { isNetwork: true });
    const send = vi.fn().mockRejectedValueOnce(lost).mockResolvedValueOnce(stored);
    const api = service({ preparePublish: vi.fn(input => ({ payload: { ...input, idempotency_key: 'k-1' }, send })) });
    render(<HousingConfirmationDialog contractId="contract-1" service={api} onClose={vi.fn()} />);
    await fillForm();
    fireEvent.click(screen.getByRole('button', { name: 'Vorschau prüfen' }));
    await screen.findByText('Vorläufige Vorschau geprüft');
    confirmAll();
    fireEvent.click(screen.getByRole('button', { name: 'Freigeben und Original speichern' }));

    expect(await screen.findByText('Verbindung unterbrochen')).toBeInTheDocument();
    expect(screen.getByLabelText(/^Tatsächlicher Einzug/)).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Unverändert erneut senden' }));
    await screen.findByText(/als unveränderliches Original gespeichert/);
    expect(send.mock.calls[1][0]).toBe(send.mock.calls[0][0]);
  });

  it('read-only roles see stored confirmations but no form', async () => {
    authState.user = { id: 'tax-1', role: 'readonly' };
    authState.write = [];
    const api = service({ listHistory: vi.fn(async () => ({ items: [stored], next_cursor: null })) });
    render(<HousingConfirmationDialog contractId="contract-1" service={api} onClose={vi.fn()} />);

    expect(await screen.findByText(/Nur Lesezugriff/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/^Tatsächlicher Einzug/)).toBeNull();
    expect(screen.queryByRole('button', { name: 'Korrektur erstellen' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'PDF öffnen' }));
    expect(await screen.findByTestId('pdf')).toHaveTextContent('/uploads/housing-confirmations/doc-1.pdf');
  });

  it('a correction starts from the stored facts and names the original', async () => {
    const api = service({ listHistory: vi.fn(async () => ({ items: [stored], next_cursor: null })) });
    render(<HousingConfirmationDialog contractId="contract-1" service={api} onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Korrektur erstellen' }));

    expect(screen.getByLabelText(/^Tatsächlicher Einzug/)).toHaveValue('2026-02-03');
    expect(screen.getByLabelText('Vollständiger Name 1')).toHaveValue('Mia Muster');
    fireEvent.click(screen.getByRole('button', { name: 'Vorschau prüfen' }));
    await screen.findByText('Vorläufige Vorschau geprüft');
    expect(api.preview.mock.calls[0][0].correctionOf).toEqual({ document_id: 'doc-1', version_id: 'ver-1' });
  });

  it('asks before discarding unsaved details and forgets everything when access is lost', async () => {
    const onClose = vi.fn();
    const denied = Object.assign(new Error('Keine Berechtigung'), { statusCode: 403 });
    const api = service({ preview: vi.fn(async () => { throw denied; }) });
    render(<HousingConfirmationDialog contractId="contract-1" service={api} onClose={onClose} />);
    await fillForm();

    fireEvent.click(screen.getAllByRole('button', { name: 'Schließen' })[0]);
    expect(screen.getByText('Ungespeicherte Angaben verwerfen?')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Weiter bearbeiten' }));
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Vorschau prüfen' }));
    expect(await screen.findByText(/in diesem Zugriff nicht verfügbar/)).toBeInTheDocument();
    expect(screen.queryByLabelText('Vollständiger Name 1')).toBeNull();
    fireEvent.click(screen.getAllByRole('button', { name: 'Schließen' })[0]);
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});
