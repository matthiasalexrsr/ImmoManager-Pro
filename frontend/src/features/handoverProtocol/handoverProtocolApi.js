import { api } from '../../api';
import { downloadFile } from '../partyWorkspace/files';

const HASH = /^[a-f0-9]{64}$/;
const encode = value => encodeURIComponent(String(value));
const base = id => `/handover-protocols/${encode(id)}`;

function detailOrFail(value) {
  if (!value || typeof value !== 'object' || !value.protocol?.id || !Array.isArray(value.rooms)
      || !Array.isArray(value.defects) || !Array.isArray(value.keys) || !Array.isArray(value.meter_readings)
      || !Array.isArray(value.photos) || !Array.isArray(value.meters) || !value.state || !value.source) {
    throw new Error('invalid_handover_detail');
  }
  return value;
}

/** The PDF bytes, and exactly the reviewed ones. */
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
  return String(value || '').replace(/[^\p{L}\p{N}._-]+/gu, '-').replace(/^-+|-+$/g, '') || 'Protokoll';
}

export const handoverProtocolService = {
  /** The contract's protocols, the tenant change around it and a proposal (rooms, keys, meters). */
  source(contractId, protocolType = 'move_out', { signal } = {}) {
    const params = new URLSearchParams({ contract_id: contractId, protocol_type: protocolType });
    return api.get(`/handover-protocols/source?${params}`, { signal });
  },

  list({ signal } = {}) {
    return api.list('/handover-protocols', { signal });
  },

  /** A prefilled draft, or the open draft of this contract and kind ({created: false}). */
  async create(contractId, protocolType, protocolDate = null, { signal } = {}) {
    const body = { contract_id: contractId, protocol_type: protocolType };
    if (protocolDate) body.protocol_date = protocolDate;
    return detailOrFail(await api.post('/handover-protocols/from-contract', body, { signal }));
  },

  async load(id, { signal } = {}) {
    return detailOrFail(await api.get(`${base(id)}/detail`, { signal }));
  },

  async save(id, payload, { signal } = {}) {
    return detailOrFail(await api.put(`${base(id)}/content`, payload, { signal }));
  },

  uploadPhoto(id, file, { roomId = null, defectId = null, meterReadingId = null, caption = '' } = {}, { signal } = {}) {
    const form = new FormData();
    form.append('file', file);
    if (caption) form.append('caption', caption);
    if (roomId) form.append('room_id', roomId);
    if (defectId) form.append('defect_id', defectId);
    if (meterReadingId) form.append('meter_reading_id', meterReadingId);
    return api.upload(`${base(id)}/photos`, form, { signal });
  },

  deletePhoto(id, photoId, { signal } = {}) {
    return api.del(`${base(id)}/photos/${encode(photoId)}`, { signal });
  },

  async followUp(id, defectId, { resolved_at = null, resolution_note = null }, { signal } = {}) {
    return detailOrFail(await api.patch(`${base(id)}/defects/${encode(defectId)}/follow-up`,
      { resolved_at: resolved_at || null, resolution_note: resolution_note || null }, { signal }));
  },

  async preview(id, { signal } = {}) {
    const value = await api.post(`${base(id)}/preview`, {}, { signal });
    if (!value || !HASH.test(value.review_hash || '') || !HASH.test(value.pdf_sha256 || '')
        || !Array.isArray(value.problems)) {
      throw new Error('invalid_handover_preview');
    }
    return value;
  },

  /** The reviewed PDF as a private object URL; the caller revokes it. */
  async previewPdfUrl(id, preview, { signal } = {}) {
    const blob = await verifiedPdf(await api.postBlob(`${base(id)}/preview-pdf`, {}, { signal }), preview?.pdf_sha256);
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    return URL.createObjectURL(blob);
  },

  async finalize(id, { idempotencyKey, reviewHash }, { signal } = {}) {
    if (!HASH.test(reviewHash || '') || !idempotencyKey) throw new Error('invalid_handover_preview');
    return detailOrFail(await api.post(`${base(id)}/finalize`, {
      idempotency_key: idempotencyKey, review_hash: reviewHash, confirmed_content: true, confirmed_signatures: true,
    }, { signal }));
  },

  async startCorrection(id, { signal } = {}) {
    return detailOrFail(await api.post(`${base(id)}/corrections`, {}, { signal }));
  },

  remove(id, { signal } = {}) {
    return api.del(base(id), { signal });
  },

  downloadOriginal(detail, { signal } = {}) {
    const { protocol, source, original } = detail;
    const kind = protocol.protocol_type === 'move_in' ? 'Einzug' : 'Auszug';
    return downloadFile(original.file_url,
      `Uebergabeprotokoll-${kind}-${safeName(source.contract.contract_number)}-${protocol.protocol_date}.pdf`,
      { signal });
  },
};
