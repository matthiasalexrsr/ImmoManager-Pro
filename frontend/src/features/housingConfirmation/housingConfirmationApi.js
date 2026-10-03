import { api } from '../../api';

const HASH = /^[a-f0-9]{64}$/;
const isObject = value => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
const isString = value => typeof value === 'string' && Boolean(value);
const encode = value => encodeURIComponent(String(value));

function sourceEtags(value) {
  if (!isObject(value)) throw new Error('invalid_housing_source');
  for (const key of ['portfolio', 'contract', 'property', 'unit', 'tenant']) {
    if (!isString(value[key])) throw new Error('invalid_housing_source');
  }
  if (!(value.wizard_revision == null || isString(value.wizard_revision))) {
    throw new Error('invalid_housing_source');
  }
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
  const contract = value.source.contract;
  const property = value.source.property;
  const unit = value.source.unit;
  if (!isString(contract.contract_number) || !isString(property.name) || !isString(unit.label)) {
    throw new Error('invalid_housing_source');
  }
  const etags = sourceEtags(value.source_etags);
  return {
    contract_id: contractId,
    contract_number: contract.contract_number,
    property_label: property.name,
    unit_label: unit.label,
    source: value.source,
    source_etags: etags,
    suggestions: {
      housing_provider_name: value.suggestions.housing_provider_name ?? null,
      housing_provider_address: value.suggestions.housing_provider_address ?? null,
      owner_name: value.suggestions.owner_name ?? null,
      dwelling_address: value.suggestions.apartment_address ?? null,
      dwelling_label: value.suggestions.apartment_label ?? null,
      main_tenant_name: Array.isArray(value.suggestions.resident_names)
        ? value.suggestions.resident_names[0] ?? null
        : null,
    },
    reference_dates: {
      contract_start_date: value.suggestions.contract_start_date_for_reference ?? contract.start_date ?? null,
      handover_date: null,
      actual_move_in_date: value.suggestions.actual_move_in_date ?? null,
    },
    policy: { ...value.policy },
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
    review: value.review,
    size_bytes: value.size_bytes,
    person_count: residents.length,
    warnings: [],
    signature_recorded: value.signature_recorded === true,
    authority_transmission_recorded: value.authority_transmission_recorded === true,
  };
}

function validateCertificateData(value) {
  if (!isObject(value)
      || !isString(value.housing_provider_name)
      || !isString(value.housing_provider_address)
      || typeof value.owner_same_as_provider !== 'boolean'
      || !(value.owner_name == null || isString(value.owner_name))
      || !isString(value.move_in_date)
      || !isString(value.issue_date)
      || !isString(value.apartment_address)
      || !(value.apartment_label == null || isString(value.apartment_label))
      || !isString(value.issuer_name)
      || !['housing_provider', 'authorized_person'].includes(value.issuer_role)
      || !Array.isArray(value.residents)
      || value.residents.length < 1
      || !value.residents.every(isString)) {
    throw new Error('invalid_housing_history');
  }
  if (value.owner_same_as_provider && value.owner_name != null) throw new Error('invalid_housing_history');
  if (!value.owner_same_as_provider && !isString(value.owner_name)) throw new Error('invalid_housing_history');
  return { ...value, residents: [...value.residents] };
}

export function mapHousingRecord(value) {
  if (!isObject(value) || !isString(value.document_id) || !isString(value.version_id)
      || !isString(value.contract_id) || !HASH.test(value.review_hash || '')
      || !HASH.test(value.pdf_sha256 || '') || !isObject(value.data)
      || !isString(value.created_at)
      || !(value.correction_of == null || (
        isObject(value.correction_of)
        && isString(value.correction_of.document_id)
        && isString(value.correction_of.version_id)
      ))) {
    throw new Error('invalid_housing_history');
  }
  const data = validateCertificateData(value.data);
  return {
    id: value.document_id,
    document_id: value.document_id,
    version_id: value.version_id,
    contract_id: value.contract_id,
    review_hash: value.review_hash,
    pdf_sha256: value.pdf_sha256,
    data,
    issue_date: value.data.issue_date,
    correction_of: value.correction_of ? { ...value.correction_of } : null,
    created_at: value.created_at,
    signature_recorded: value.signature_recorded === true,
    authority_transmission_recorded: value.authority_transmission_recorded === true,
  };
}

export function mapHousingPage(value) {
  if (!isObject(value) || !Array.isArray(value.items) || typeof value.has_more !== 'boolean'
      || !(value.next_cursor == null || isString(value.next_cursor))
      || (value.has_more && !value.next_cursor)
      || (!value.has_more && value.next_cursor != null)) {
    throw new Error('invalid_housing_history_page');
  }
  return {
    items: value.items.map(mapHousingRecord),
    has_more: value.has_more,
    next_cursor: value.next_cursor,
  };
}

export function buildPreviewRequest({ data, sourceEtags, correctionOf = null }) {
  return {
    data,
    source_etags: { ...sourceEtags },
    correction_of: correctionOf ? { ...correctionOf } : null,
  };
}

export function buildSaveRequest({
  data,
  sourceEtags,
  correctionOf = null,
  preview,
  confirmations,
  idempotencyKey = `housing-confirmation:${crypto.randomUUID()}`,
}) {
  if (!preview || !HASH.test(preview.review_hash || '')) throw new Error('invalid_housing_preview');
  if (!confirmations
      || confirmations.confirmed_actual_move_in !== true
      || confirmations.confirmed_authority !== true
      || confirmations.confirmed_residents !== true) {
    throw new Error('housing_confirmations_required');
  }
  return {
    ...buildPreviewRequest({ data, sourceEtags, correctionOf }),
    idempotency_key: idempotencyKey,
    review_hash: preview.review_hash,
    confirmed_actual_move_in: confirmations.confirmed_actual_move_in === true,
    confirmed_authority: confirmations.confirmed_authority === true,
    confirmed_residents: confirmations.confirmed_residents === true,
  };
}

async function verifiedPdf(path, { signal } = {}) {
  const blob = await api.getBlob(path, { signal });
  const bytes = new Uint8Array(await blob.slice(0, 8).arrayBuffer());
  const header = String.fromCharCode(...bytes);
  if (!header.startsWith('%PDF-')) throw new Error('invalid_housing_pdf');
  return blob.type === 'application/pdf' ? blob : new Blob([blob], { type: 'application/pdf' });
}

export const housingConfirmationService = {
  async loadSource(contractId, { signal } = {}) {
    const value = await api.get(
      `/contracts/${encode(contractId)}/housing-confirmations/source`,
      { signal },
    );
    return mapHousingSource(value, contractId);
  },

  async listHistory(contractId, { cursor = null, limit = 25, signal } = {}) {
    const params = new URLSearchParams({ limit: String(limit) });
    if (cursor) params.set('after', cursor);
    const value = await api.get(
      `/contracts/${encode(contractId)}/housing-confirmations?${params.toString()}`,
      { signal },
    );
    return mapHousingPage(value);
  },

  async preview({ contractId, data, sourceEtags, correctionOf }, { signal } = {}) {
    const payload = buildPreviewRequest({ data, sourceEtags, correctionOf });
    const value = await api.post(
      `/contracts/${encode(contractId)}/housing-confirmations/preview`,
      payload,
      { signal },
    );
    return mapHousingPreview(value);
  },

  preparePublish({ contractId, data, sourceEtags, correctionOf, preview, confirmations }) {
    const payload = buildSaveRequest({
      data,
      sourceEtags,
      correctionOf,
      preview,
      confirmations,
    });
    return {
      payload,
      send: async (command, { signal } = {}) => mapHousingRecord(await api.post(
        `/contracts/${encode(contractId)}/housing-confirmations`,
        command,
        { signal },
      )),
    };
  },

  async openOriginal(item, { signal } = {}) {
    const path = `/contracts/${encode(item.contract_id)}/housing-confirmations/${encode(item.document_id)}/download`;
    const blob = await verifiedPdf(path, { signal });
    const url = URL.createObjectURL(blob);
    const opened = window.open(url, '_blank', 'noopener,noreferrer');
    if (!opened) {
      URL.revokeObjectURL(url);
      throw new Error('pdf_open_blocked');
    }
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  },
};
