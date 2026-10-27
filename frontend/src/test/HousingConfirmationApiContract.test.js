import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  getBlob: vi.fn(),
  postBlob: vi.fn(),
}));

vi.mock('../api', () => ({ api: apiMock }));
const downloadMock = vi.hoisted(() => vi.fn(async () => {}));
vi.mock('../features/partyWorkspace/files', () => ({ downloadFile: downloadMock }));

import {
  buildPreviewRequest,
  buildSaveRequest,
  housingConfirmationService,
  mapHousingPage,
  mapHousingPreview,
  mapHousingRecord,
  mapHousingSource,
} from '../features/housingConfirmation/housingConfirmationApi';

const hash = char => char.repeat(64);
const sourceEtags = {
  portfolio: '"portfolio-etag"',
  contract: '"contract-etag"',
  property: '"property-etag"',
  unit: '"unit-etag"',
  tenant: '"tenant-etag"',
  wizard_revision: hash('a'),
};
const certificate = {
  housing_provider_name: 'Wohnungsgeber GmbH',
  housing_provider_address: 'Weg 1\n12345 Berlin',
  owner_same_as_provider: false,
  owner_name: 'Eigentümerin Beispiel',
  move_in_date: '2026-10-15',
  issue_date: '2026-10-16',
  apartment_address: 'Parkweg 1\n12345 Berlin',
  apartment_label: '2. OG links',
  issuer_name: 'Beauftragte Person',
  issuer_role: 'authorized_person',
  residents: ['Alex Beispiel', 'Sam Beispiel'],
};

function rawSource() {
  return {
    contract_id: 'contract-1',
    source: {
      portfolio: { id: 'portfolio-1', name: 'Portfolio', owner_name: 'Eigentümerin Beispiel' },
      property: {
        id: 'property-1', portfolio_id: 'portfolio-1', name: 'Haus am Park',
        address_line: 'Parkweg 1', postal_code: '12345', city: 'Berlin', country: 'DE',
      },
      unit: { id: 'unit-1', property_id: 'property-1', label: '2. OG links' },
      contract: {
        id: 'contract-1', contract_number: 'MV-1', property_id: 'property-1',
        unit_id: 'unit-1', tenant_id: 'tenant-1', status: 'active',
        start_date: '2026-10-01', end_date: null,
      },
      tenant: { id: 'tenant-1', full_name: 'Hauptmieter Beispiel' },
      wizard: null,
      etags: sourceEtags,
    },
    source_etags: sourceEtags,
    suggestions: {
      housing_provider_name: null,
      housing_provider_address: null,
      owner_name: 'Eigentümerin Beispiel',
      apartment_address: 'Parkweg 1\n12345 Berlin\nDE',
      apartment_label: '2. OG links',
      resident_names: ['Hauptmieter Beispiel'],
      contract_start_date_for_reference: '2026-10-01',
      actual_move_in_date: null,
    },
    policy: {
      main_tenant_is_suggestion_only: true,
      contract_start_is_not_actual_move_in: true,
      handover_date_is_not_actual_move_in: true,
      additional_residents_require_explicit_input: true,
    },
  };
}

function rawPreview() {
  return {
    review_hash: hash('b'),
    pdf_sha256: hash('c'),
    review: {
      format_version: 1,
      data: certificate,
      source: rawSource().source,
      correction_of: null,
      pdf_sha256: hash('c'),
    },
    size_bytes: 2048,
    state: 'preview',
    signature_recorded: false,
    authority_transmission_recorded: false,
  };
}

function rawRecord(overrides = {}) {
  return {
    document_id: 'document-1',
    version_id: 'version-1',
    contract_id: 'contract-1',
    review_hash: hash('b'),
    pdf_sha256: hash('c'),
    data: certificate,
    correction_of: null,
    created_at: '2026-10-16T12:00:00+00:00',
    file_url: '/uploads/housing-confirmations/document-1.pdf',
    download_url: '/contracts/contract-1/housing-confirmations/document-1/download',
    version_download_url: '/documents/document-1/versions/version-1/download',
    signature_recorded: false,
    authority_transmission_recorded: false,
    ...overrides,
  };
}

describe('housing confirmation backend contract', () => {
  beforeEach(() => vi.clearAllMocks());

  it('maps the exact authorized source without inventing an actual move-in date', async () => {
    const mapped = mapHousingSource(rawSource(), 'contract-1');
    expect(mapped.contract_number).toBe('MV-1');
    expect(mapped.property_label).toBe('Haus am Park');
    expect(mapped.unit_label).toBe('2. OG links');
    expect(mapped.suggestions.main_tenant_name).toBe('Hauptmieter Beispiel');
    expect(mapped.reference_dates.contract_start_date).toBe('2026-10-01');
    expect(mapped.reference_dates).not.toHaveProperty('actual_move_in_date');
    expect(mapped.source_etags).toEqual(sourceEtags);

    apiMock.get.mockResolvedValue(rawSource());
    await expect(housingConfirmationService.loadSource('contract-1')).resolves.toMatchObject({
      contract_id: 'contract-1',
      contract_number: 'MV-1',
    });
    expect(apiMock.get).toHaveBeenCalledWith(
      '/contracts/contract-1/housing-confirmations/source',
      { signal: undefined },
    );
  });

  it('sends PreviewRequest exactly with source_etags and correction reference', async () => {
    const correction = { document_id: 'document-old', version_id: 'version-old' };
    const payload = buildPreviewRequest({
      data: certificate,
      sourceEtags,
      correctionOf: correction,
    });
    expect(payload).toEqual({
      data: certificate,
      source_etags: sourceEtags,
      correction_of: correction,
    });

    apiMock.post.mockResolvedValue(rawPreview());
    const preview = await housingConfirmationService.preview({
      contractId: 'contract-1',
      data: certificate,
      sourceEtags,
      correctionOf: correction,
    });
    expect(preview).toEqual(mapHousingPreview(rawPreview()));
    expect(apiMock.post).toHaveBeenCalledWith(
      '/contracts/contract-1/housing-confirmations/preview',
      payload,
      { signal: undefined },
    );
  });

  it('builds SaveRequest with all three confirmations and exact reviewed hash', async () => {
    const preview = mapHousingPreview(rawPreview());
    const payload = buildSaveRequest({
      data: certificate,
      sourceEtags,
      correctionOf: null,
      preview,
      confirmations: {
        confirmed_actual_move_in: true,
        confirmed_authority: true,
        confirmed_residents: true,
      },
      idempotencyKey: 'housing-key-1',
    });
    expect(payload).toEqual({
      data: certificate,
      source_etags: sourceEtags,
      correction_of: null,
      idempotency_key: 'housing-key-1',
      review_hash: hash('b'),
      confirmed_actual_move_in: true,
      confirmed_authority: true,
      confirmed_residents: true,
    });

    apiMock.post.mockResolvedValue(rawRecord());
    const prepared = housingConfirmationService.preparePublish({
      contractId: 'contract-1',
      data: certificate,
      sourceEtags,
      correctionOf: null,
      preview,
      confirmations: {
        confirmed_actual_move_in: true,
        confirmed_authority: true,
        confirmed_residents: true,
      },
    });
    prepared.payload.idempotency_key = 'housing-key-2';
    await expect(prepared.send(prepared.payload)).resolves.toEqual(mapHousingRecord(rawRecord()));
    expect(apiMock.post).toHaveBeenCalledWith(
      '/contracts/contract-1/housing-confirmations',
      prepared.payload,
      { signal: undefined },
    );
  });

  it('uses the opaque after cursor and maps immutable original history', async () => {
    apiMock.get.mockResolvedValue({
      items: [rawRecord({
        correction_of: { document_id: 'document-old', version_id: 'version-old' },
      })],
      has_more: true,
      next_cursor: 'opaque-next',
    });
    const page = await housingConfirmationService.listHistory(
      'contract-1',
      { cursor: 'opaque-current', limit: 25 },
    );
    expect(page).toEqual(mapHousingPage({
      items: [rawRecord({
        correction_of: { document_id: 'document-old', version_id: 'version-old' },
      })],
      has_more: true,
      next_cursor: 'opaque-next',
    }));
    expect(apiMock.get).toHaveBeenCalledWith(
      '/contracts/contract-1/housing-confirmations?limit=25&after=opaque-current',
      { signal: undefined },
    );
  });

  it('shows only the exact reviewed PDF bytes as a private object URL', async () => {
    const bytes = new TextEncoder().encode('%PDF-1.7\nbody');
    const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))]
      .map(byte => byte.toString(16).padStart(2, '0')).join('');
    apiMock.postBlob.mockResolvedValue(new Blob([bytes], { type: 'application/octet-stream' }));
    const create = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:housing-pdf');
    const input = { contractId: 'contract-1', data: certificate, sourceEtags, correctionOf: null };

    await expect(housingConfirmationService.previewPdfUrl({ ...input, preview: { pdf_sha256: digest } }))
      .resolves.toBe('blob:housing-pdf');
    expect(apiMock.postBlob).toHaveBeenCalledWith('/contracts/contract-1/housing-confirmations/preview-pdf',
      buildPreviewRequest(input), { signal: undefined });
    expect(create.mock.calls[0][0].type).toBe('application/pdf');

    create.mockClear();
    await expect(housingConfirmationService.previewPdfUrl({ ...input, preview: { pdf_sha256: hash('d') } }))
      .rejects.toThrow('nicht mit der geprüften Fassung');
    apiMock.postBlob.mockResolvedValue(new Blob(['<html>login</html>']));
    await expect(housingConfirmationService.previewPdfUrl({ ...input, preview: { pdf_sha256: digest } }))
      .rejects.toThrow('kein PDF');
    expect(create).not.toHaveBeenCalled();
    create.mockRestore();
  });

  it('downloads the original through the session-bound file path with a readable name', async () => {
    await housingConfirmationService.downloadOriginal(mapHousingRecord(rawRecord()), 'MV 1/2026');
    expect(downloadMock).toHaveBeenCalledWith('/uploads/housing-confirmations/document-1.pdf',
      'Wohnungsgeberbestaetigung-MV-1-2026-2026-10-16.pdf', { signal: undefined });
  });

  it('rejects a history page whose cursor contradicts has_more', () => {
    expect(() => mapHousingPage({ items: [], has_more: true, next_cursor: null })).toThrow('invalid_housing_history_page');
    expect(() => mapHousingRecord(rawRecord({ data: { ...certificate, owner_same_as_provider: true } })))
      .toThrow('invalid_housing_history');
  });
});
