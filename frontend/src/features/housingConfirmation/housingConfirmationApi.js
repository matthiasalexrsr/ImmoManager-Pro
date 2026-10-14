import { api } from '../../api';
import { downloadFile } from '../partyWorkspace/files';

const HASH = /^[a-f0-9]{64}$/;
const isObject = value => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
const isString = value => typeof value === 'string' && Boolean(value);
const encode = value => encodeURIComponent(String(value));
const base = contractId => `/contracts/${encode(contractId)}/housing-confirmations`;

function sourceEtags(value) {
  if (!isObject(value)) throw new Error('invalid_housing_source');
  for (const key of ['portfolio', 'contract', 'property', 'unit', 'tenant']) {
    if (!isString(value[key])) throw new Error('invalid_housing_source');
  }
  if (!(value.wizard_revision == null || isString(value.wizard_revision))) throw new Error('invalid_housing_source');
  return { ...value };
}

export function mapHousingSource(value, contractId) {
  if (!isObject(value) || value.contract_id !== contractId || !isObject(value.source)
      || !isObject(value.source.contract) || !isObject(value.source.property)
      || !isObject(value.source.unit) || !isObject(value.source.tenant)
      || value.source.contract.id !== contractId || !isObject(value.suggestions)
      || !isObject(value.policy)) {
    throw new Error('invalid_housing_source');
  }
  const { contract, property, unit } = value.source;
  if (!isString(contract.contract_number) || !isString(property.name) || !isString(unit.label)) {
    throw new Error('invalid_housing_source');
  }
  return {
    contract_id: contractId,
    contract_number: contract.contract_number,
    property_label: property.name,
    unit_label: unit.label,
    source_etags: sourceEtags(value.source_etags),
    suggestions: {
      housing_provider_name: value.suggestions.housing_provider_name ?? null,
      housing_provider_address: value.suggestions.housing_provider_address ?? null,
      owner_name: value.suggestions.owner_name ?? null,
      dwelling_address: value.suggestions.apartment_address ?? null,
      dwelling_label: value.suggestions.apartment_label ?? null,
      main_tenant_name: Array.isArray(value.suggestions.resident_names)
        ? value.suggestions.resident_names[0] ?? null : null,
    },
    reference_dates: {
      contract_start_date: value.suggestions.contract_start_date_for_reference ?? contract.start_date ?? null,
    },
  };
}

export function mapHousingPreview(value) {
  if (!isObject(value) || !HASH.test(value.review_hash || '') || !HASH.test(value.pdf_sha256 || '')
      || !isObject(value.review) || !isObject(value.review.data)
      || value.state !== 'preview' || !Number.isInteger(value.size_bytes) || value.size_bytes < 1) {
    throw new Error('invalid_housing_preview');
  }
  const residents = value.review.data.residents;
  if (!Array.isArray(residents) || residents.length < 1) throw new Error('invalid_housing_preview');
  return {
    review_hash: value.review_hash,
    pdf_sha256: value.pdf_sha256,
    size_bytes: value.size_bytes,
    person_count: residents.length,
  };
}

function validateCertificateData(value) {
  if (!isObject(value) || !isString(value.housing_provider_name) || !isString(value.housing_provider_address)
      || typeof value.owner_same_as_provider !== 'boolean'
      || !(value.owner_name == null || isString(value.owner_name))
      || !isString(value.move_in_date) || !isString(value.issue_date) || !isString(value.apartment_address)
      || !(value.apartment_label == null || isString(value.apartment_label))
      || !isString(value.issuer_name) || !['housing_provider', 'authorized_person'].includes(value.issuer_role)
      || !Array.isArray(value.residents) || value.residents.length < 1 || !value.residents.every(isString)) {
    throw new Error('invalid_housing_history');
  }
  if (value.owner_same_as_provider ? value.owner_name != null : !isString(value.owner_name)) {
    throw new Error('invalid_housing_history');
  }
  return { ...value, residents: [...value.residents] };
}

export function mapHousingRecord(value) {
  if (!isObject(value) || !isString(value.document_id) || !isString(value.version_id)
      || !isString(value.contract_id) || !HASH.test(value.review_hash || '') || !HASH.test(value.pdf_sha256 || '')
      || !isObject(value.data) || !isString(value.created_at) || !isString(value.file_url)
      || !(value.correction_of == null || (isObject(value.correction_of)
        && isString(value.correction_of.document_id) && isString(value.correction_of.version_id)))) {
    throw new Error('invalid_housing_history');
  }
  const data = validateCertificateData(value.data);
  return {
    id: value.document_id,
    document_id: value.document_id,
    version_id: value.version_id,
    contract_id: value.contract_id,
    pdf_sha256: value.pdf_sha256,
    data,
    issue_date: data.issue_date,
    correction_of: value.correction_of ? { ...value.correction_of } : null,
    created_at: value.created_at,
    file_url: value.file_url,
  };
}

export function mapHousingPage(value) {
  if (!isObject(value) || !Array.isArray(value.items) || typeof value.has_more !== 'boolean'
      || !(value.next_cursor == null || isString(value.next_cursor))
      || (value.has_more !== Boolean(value.next_cursor))) {
    throw new Error('invalid_housing_history_page');
  }
  return { items: value.items.map(mapHousingRecord), next_cursor: value.next_cursor };
}

export function buildPreviewRequest({ data, sourceEtags: etags, correctionOf = null }) {
  return { data, source_etags: { ...etags }, correction_of: correctionOf ? { ...correctionOf } : null };
}

export function buildSaveRequest({ data, sourceEtags: etags, correctionOf = null, preview, confirmations,
  idempotencyKey = `housing-confirmation:${crypto.randomUUID()}` }) {
  if (!preview || !HASH.test(preview.review_hash || '')) throw new Error('invalid_housing_preview');
  if (confirmations?.confirmed_actual_move_in !== true || confirmations?.confirmed_authority !== true
      || confirmations?.confirmed_residents !== true) {
    throw new Error('housing_confirmations_required');
  }
  return {
    ...buildPreviewRequest({ data, sourceEtags: etags, correctionOf }),
    idempotency_key: idempotencyKey,
    review_hash: preview.review_hash,
    confirmed_actual_move_in: true,
    confirmed_authority: true,
    confirmed_residents: true,
  };
}

/** The bytes are a PDF, and exactly the reviewed one. */
async function verifiedPdf(blob, expectedSha256) {
  const header = String.fromCharCode(...new Uint8Array(await blob.slice(0, 5).arrayBuffer()));
  if (header !== '%PDF-') throw new Error('Die Vorschau ist kein PDF.');
  if (expectedSha256 && globalThis.crypto?.subtle) {
    const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', await blob.arrayBuffer()));
    const hex = [...digest].map(byte => byte.toString(16).padStart(2, '0')).join('');
    if (hex !== expectedSha256) throw new Error('Die Vorschau stimmt nicht mit der geprüften Fassung überein.');
  }
  return blob.type === 'application/pdf' ? blob : new Blob([blob], { type: 'application/pdf' });
}

function safeName(value) {
  return String(value || '').replace(/[^\p{L}\p{N}._-]+/gu, '-').replace(/^-+|-+$/g, '') || 'Vertrag';
}

export const housingConfirmationService = {
  async loadSource(contractId, { signal } = {}) {
    return mapHousingSource(await api.get(`${base(contractId)}/source`, { signal }), contractId);
  },

  async listHistory(contractId, { cursor = null, limit = 25, signal } = {}) {
    const params = new URLSearchParams({ limit: String(limit) });
    if (cursor) params.set('after', cursor);
    return mapHousingPage(await api.get(`${base(contractId)}?${params}`, { signal }));
  },

  async preview({ contractId, data, sourceEtags: etags, correctionOf }, { signal } = {}) {
    const payload = buildPreviewRequest({ data, sourceEtags: etags, correctionOf });
    return mapHousingPreview(await api.post(`${base(contractId)}/preview`, payload, { signal }));
  },

  /** The reviewed PDF as a private object URL; the caller revokes it. */
  async previewPdfUrl({ contractId, data, sourceEtags: etags, correctionOf, preview }, { signal } = {}) {
    const payload = buildPreviewRequest({ data, sourceEtags: etags, correctionOf });
    const blob = await verifiedPdf(await api.postBlob(`${base(contractId)}/preview-pdf`, payload, { signal }),
      preview?.pdf_sha256);
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    return URL.createObjectURL(blob);
  },

  preparePublish({ contractId, ...input }) {
    const payload = buildSaveRequest(input);
    return {
      payload,
      send: async (command, { signal } = {}) => mapHousingRecord(await api.post(base(contractId), command, { signal })),
    };
  },

  downloadOriginal(item, contractNumber, { signal } = {}) {
    return downloadFile(item.file_url, `Wohnungsgeberbestaetigung-${safeName(contractNumber)}-${item.issue_date}.pdf`,
      { signal });
  },
};
