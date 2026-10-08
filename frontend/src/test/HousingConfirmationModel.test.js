import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  blankHousingForm,
  certificateDataFromForm,
  formFromCertificateData,
  housingBindingKey,
  isConflictOutcome,
  isPrivateForgetOutcome,
  isUnknownOutcome,
  validateHousingForm,
} from '../features/housingConfirmation/housingConfirmationModel';
import {
  buildSaveRequest,
  housingConfirmationService,
  mapHousingPage,
  mapHousingSource,
} from '../features/housingConfirmation/housingConfirmationApi';

const data = {
  housing_provider_name: 'Linda Reiser', housing_provider_address: 'Prießnitzstraße 4\n01099 Dresden',
  owner_same_as_provider: true, owner_name: null, move_in_date: '2026-02-03', issue_date: '2026-10-07',
  apartment_address: 'Bautzner Straße 61\n01099 Dresden', apartment_label: 'WE 3', issuer_name: 'Linda Reiser',
  issuer_role: 'housing_provider', residents: ['Mia Muster', 'Zoë Beispiel'],
};
const etags = { portfolio: '"p"', contract: '"c"', property: '"pr"', unit: '"u"', tenant: '"t"', wizard_revision: null };

describe('housing confirmation model', () => {
  it('keeps the actual move-in empty and turns a filled form into the certificate data', () => {
    expect(blankHousingForm().actual_move_in_date).toBe('');
    const form = formFromCertificateData(data);
    expect(certificateDataFromForm(form)).toEqual(data);
    expect(validateHousingForm(form).valid).toBe(true);
    expect(validateHousingForm(form, { forPublish: true }).errors).toEqual(
      ['confirmed_actual_move_in', 'confirmed_authority', 'confirmed_residents']);
    expect(validateHousingForm({ ...form, owner_relation: 'different', owner_name: '' }).errors).toContain('owner_name');
  });

  it('binds private state to the contract, the user, the role and the write areas', () => {
    const user = { id: 'u1', role: 'verwalter' };
    const key = housingBindingKey('c1', user, null);
    expect(housingBindingKey('c1', user, null)).toBe(key);
    expect(housingBindingKey('c2', user, null)).not.toBe(key);
    expect(housingBindingKey('c1', { ...user, role: 'techniker' }, null)).not.toBe(key);
    expect(housingBindingKey('c1', user, ['/documents'])).not.toBe(key);
    expect(housingBindingKey('c1', { ...user, is_active: false }, null)).toBe('');
  });

  it('sorts outcomes: lost answers can be retried, conflicts reloaded, access errors forget', () => {
    expect(isUnknownOutcome({ isNetwork: true })).toBe(true);
    expect(isUnknownOutcome({ statusCode: 503 })).toBe(true);
    expect(isConflictOutcome({ statusCode: 412 })).toBe(true);
    expect(isPrivateForgetOutcome({ statusCode: 403 })).toBe(true);
    expect(isUnknownOutcome({ statusCode: 409 })).toBe(false);
  });
});

describe('housing confirmation API contract', () => {
  afterEach(() => vi.restoreAllMocks());

  it('maps the source and refuses one for another contract', () => {
    const raw = {
      contract_id: 'c1', source_etags: etags, policy: {},
      source: { contract: { id: 'c1', contract_number: 'V-1', start_date: '2024-01-01' }, property: { name: 'Haus' },
        unit: { label: 'WE 3' }, tenant: { full_name: 'Mia Muster' } },
      suggestions: { resident_names: ['Mia Muster'], apartment_address: 'Bautzner Straße 61', actual_move_in_date: null },
    };
    const mapped = mapHousingSource(raw, 'c1');
    expect(mapped.suggestions.main_tenant_name).toBe('Mia Muster');
    expect(mapped.reference_dates.contract_start_date).toBe('2024-01-01');
    expect(() => mapHousingSource(raw, 'c2')).toThrow('invalid_housing_source');
  });

  it('needs all three confirmations before a publication is built', () => {
    const preview = { review_hash: 'a'.repeat(64) };
    const confirmations = { confirmed_actual_move_in: true, confirmed_authority: true, confirmed_residents: false };
    expect(() => buildSaveRequest({ data, sourceEtags: etags, preview, confirmations })).toThrow('housing_confirmations_required');
    const request = buildSaveRequest({ data, sourceEtags: etags, preview,
      confirmations: { ...confirmations, confirmed_residents: true }, idempotencyKey: 'k1' });
    expect(request).toMatchObject({ idempotency_key: 'k1', review_hash: 'a'.repeat(64), correction_of: null });
  });

  it('rejects an inconsistent history page', () => {
    expect(() => mapHousingPage({ items: [], has_more: true, next_cursor: null })).toThrow();
    expect(mapHousingPage({ items: [], has_more: false, next_cursor: null }).items).toEqual([]);
  });

  it('shows only a PDF that matches the reviewed checksum', async () => {
    const bytes = new TextEncoder().encode('%PDF-1.4 test');
    const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))]
      .map(byte => byte.toString(16).padStart(2, '0')).join('');
    const { api } = await import('../api');
    vi.spyOn(api, 'postBlob').mockResolvedValue(new Blob([bytes], { type: 'application/pdf' }));
    const created = vi.fn(() => 'blob:preview');
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: created }));
    const input = { contractId: 'c1', data, sourceEtags: etags, correctionOf: null };

    await expect(housingConfirmationService.previewPdfUrl({ ...input, preview: { pdf_sha256: digest } })).resolves.toBe('blob:preview');
    await expect(housingConfirmationService.previewPdfUrl({ ...input, preview: { pdf_sha256: '0'.repeat(64) } }))
      .rejects.toThrow('geprüften Fassung');
    expect(created).toHaveBeenCalledTimes(1);
  });
});
