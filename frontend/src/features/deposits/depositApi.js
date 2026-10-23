import { api } from '../../api';

const HASH = /^[a-f0-9]{64}$/;
const encode = value => encodeURIComponent(String(value));
const base = id => `/deposits/${encode(id)}`;

function fileOrFail(value) {
  if (!value || typeof value !== 'object' || !value.deposit?.id || !Array.isArray(value.instalments)
      || !Array.isArray(value.payments) || !Array.isArray(value.settlements) || !value.source) {
    throw new Error('invalid_deposit_file');
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

export const depositService = {
  /** One page of deposit files with figures; every file counted. */
  files({ contractId = null, stage = '', query = '', skip = 0, limit = 50 } = {}, { signal } = {}) {
    const params = new URLSearchParams({ skip: String(skip), limit: String(limit) });
    if (contractId) params.set('contract_id', contractId);
    if (stage) params.set('stage', stage);
    if (query) params.set('q', query);
    return api.get(`/deposits/files?${params}`, { signal });
  },

  source(contractId, { signal } = {}) {
    return api.get(`/deposits/source?${new URLSearchParams({ contract_id: contractId })}`, { signal });
  },

  async create(agreement, { signal } = {}) {
    return fileOrFail(await api.post('/deposits/agreements', agreement, { signal }));
  },

  async load(id, { signal } = {}) {
    return fileOrFail(await api.get(`${base(id)}/file`, { signal }));
  },

  async updateAgreement(id, agreement, { signal } = {}) {
    return fileOrFail(await api.put(`${base(id)}/agreement`, agreement, { signal }));
  },

  candidates(id, { signal, skip = 0, limit = 200, query = '' } = {}) {
    const params = new URLSearchParams({ skip: String(skip), limit: String(limit) });
    if (query.trim()) params.set('q', query.trim());
    return api.get(`${base(id)}/payment-candidates?${params}`, { signal });
  },

  async addPayment(id, bookingId, amount = null, { signal } = {}) {
    const body = { booking_id: bookingId };
    if (amount !== null && amount !== '') body.amount = Number(amount);
    return fileOrFail(await api.post(`${base(id)}/payments`, body, { signal }));
  },

  async removePayment(id, paymentId, { signal } = {}) {
    return fileOrFail(await api.del(`${base(id)}/payments/${encode(paymentId)}`, { signal }));
  },

  async setRates(id, revision, rates, { signal } = {}) {
    return fileOrFail(await api.put(`${base(id)}/interest-rates`, { base_revision: revision, rates }, { signal }));
  },

  /** What was received and credited before the app's bookings began; all values empty removes it. */
  async setTakeover(id, payload, { signal } = {}) {
    return fileOrFail(await api.put(`${base(id)}/takeover`, payload, { signal }));
  },

  /** Plain records of earlier versions that can be taken over as received on their receipt date. */
  legacyCandidates({ signal } = {}) {
    return api.get('/deposits/legacy-takeover', { signal });
  },

  takeOverLegacy(depositIds, { signal } = {}) {
    return api.post('/deposits/legacy-takeover', { deposit_ids: depositIds }, { signal });
  },

  async setSecurity(id, payload, { signal } = {}) {
    return fileOrFail(await api.put(`${base(id)}/security`, payload, { signal }));
  },

  async startSettlement(id, kind, settlementDate = null, { signal } = {}) {
    const body = { kind };
    if (settlementDate) body.settlement_date = settlementDate;
    return fileOrFail(await api.post(`${base(id)}/settlements`, body, { signal }));
  },

  async saveSettlement(id, settlementId, payload, { signal } = {}) {
    return fileOrFail(await api.put(`${base(id)}/settlements/${encode(settlementId)}`, payload, { signal }));
  },

  async deleteSettlement(id, settlementId, { signal } = {}) {
    return fileOrFail(await api.del(`${base(id)}/settlements/${encode(settlementId)}`, { signal }));
  },

  async preview(id, settlementId, { signal } = {}) {
    const value = await api.post(`${base(id)}/settlements/${encode(settlementId)}/preview`, {}, { signal });
    if (!value || !HASH.test(value.review_hash || '') || !Array.isArray(value.problems)) {
      throw new Error('invalid_deposit_preview');
    }
    return value;
  },

  /** The reviewed PDF as a private object URL; the caller revokes it. */
  async previewPdfUrl(id, settlementId, preview, { signal } = {}) {
    const blob = await verifiedPdf(await api.postBlob(`${base(id)}/settlements/${encode(settlementId)}/preview-pdf`,
      {}, { signal }), preview?.pdf_sha256);
    return URL.createObjectURL(blob);
  },

  async finalize(id, settlementId, { idempotencyKey, reviewHash, payoutAccountId = null }, { signal } = {}) {
    if (!HASH.test(reviewHash || '') || !idempotencyKey) throw new Error('invalid_deposit_preview');
    return fileOrFail(await api.post(`${base(id)}/settlements/${encode(settlementId)}/finalize`, {
      idempotency_key: idempotencyKey, review_hash: reviewHash, confirmed: true,
      payout_account_id: payoutAccountId || null,
    }, { signal }));
  },

  /** The archived original as a private object URL; the caller revokes it. */
  async originalUrl(id, settlementId, expectedSha256, { signal } = {}) {
    const blob = await verifiedPdf(await api.getBlob(`${base(id)}/settlements/${encode(settlementId)}/document`,
      { signal }), expectedSha256);
    return URL.createObjectURL(blob);
  },

  remove(id, { signal } = {}) {
    return api.del(base(id), { signal });
  },
};
