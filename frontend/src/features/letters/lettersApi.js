import { api } from '../../api';

const contractRoot = id => `/contracts/${encodeURIComponent(id)}/letters`;
const HASH = /^[a-f0-9]{64}$/;

export const LETTER_FIELDS = ['recipient_name', 'recipient_address', 'issue_date', 'subject', 'salutation', 'body', 'closing', 'signature', 'appendix'];
export const letterData = values => Object.fromEntries(LETTER_FIELDS.map(key => [key, String(values?.[key] ?? '').trim()]));
export const letterSignature = (data, inputs) => JSON.stringify([letterData(data), inputs || {}]);

export const LETTERHEAD_FIELDS = [
  { name: 'sender_name', key: 'document_sender', label: 'Absender (Name oder Firma)', rows: 1, hint: 'leer: der Eigentümer laut Portfolio' },
  { name: 'sender_address', key: 'document_address', label: 'Anschrift', rows: 3, hint: 'Straße und Hausnummer, darunter PLZ und Ort' },
  { name: 'contact', key: 'document_contact', label: 'Kontakt', rows: 3, hint: 'z. B. Telefon, E-Mail, Sprechzeiten' },
  { name: 'bank', key: 'document_bank', label: 'Bankverbindung', rows: 4, hint: 'Kontoinhaber, IBAN, BIC, Bank' },
  { name: 'footer', key: 'document_footer', label: 'Fußzeile', rows: 2, hint: 'z. B. Steuernummer oder Handelsregister' },
  { name: 'signature', key: 'document_signature', label: 'Unterschriftszeile', rows: 1, hint: 'Name unter dem Gruß' },
];

export function checkPreview(preview, payload) {
  if (!HASH.test(preview?.review_hash || '') || !HASH.test(preview?.pdf_sha256 || '') || preview?.state !== 'preview'
    || preview?.review?.source_revision !== payload.source_revision || preview?.review?.pdf_sha256 !== preview.pdf_sha256
    || JSON.stringify(letterData(preview?.review?.data)) !== JSON.stringify(letterData(payload.data))
    || typeof preview.review.draft !== 'boolean') {
    throw new Error('Die Vorschau passt nicht zum aktuellen Brief. Bitte erneut erstellen.');
  }
  return preview;
}

export async function pdfHash(blob) {
  const digest = await crypto.subtle.digest('SHA-256', await blob.arrayBuffer());
  return [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, '0')).join('');
}

// Only same-origin API downloads of archived letters are followed.
export function downloadPath(value) {
  if (typeof value !== 'string' || !value.startsWith('/files/download?key=template-letters%2F')) throw new Error('Die Downloadadresse ist ungültig.');
  return value;
}

export const lettersService = {
  context: (id, options) => api.get(`${contractRoot(id)}/context`, options),
  compose: (id, payload, options) => api.post(`${contractRoot(id)}/compose`, payload, options),
  preview: (id, payload, options) => api.post(`${contractRoot(id)}/preview`, payload, options),
  previewPdf: (id, payload, options) => api.postBlob(`${contractRoot(id)}/preview-pdf`, payload, options),
  publish: (id, payload, options) => api.post(contractRoot(id), payload, options),
  original: (record, options) => api.getBlob(downloadPath(record.download_url), options),
};

export const templatesService = {
  list: (archived = false, options) => api.get(`/letter-templates${archived ? '?archived=true' : ''}`, options),
  create: (payload, options) => api.post('/letter-templates', payload, options),
  update: (id, payload, options) => api.put(`/letter-templates/${encodeURIComponent(id)}`, payload, options),
};

export const letterheadService = {
  view: options => api.get('/letterhead', options),
  catalogue: options => api.get('/auth/users/me/settings', options),
  saveField: (key, value, baseRevision, options) => api.put('/auth/users/me/settings', {
    values: { [key]: value }, base_revision: baseRevision, scope: 'global', idempotency_key: crypto.randomUUID(),
  }, options),
  logo: options => api.getBlob('/letterhead/logo', options),
  uploadLogo: (file, baseRevision, options) => {
    const form = new FormData();
    form.append('file', file);
    form.append('scope', 'global');
    form.append('base_revision', String(baseRevision));
    form.append('idempotency_key', crypto.randomUUID());
    return api.upload('/letterhead/logo', form, options);
  },
  removeLogo: (baseRevision, options) => api.del(`/letterhead/logo?scope=global&base_revision=${baseRevision}&idempotency_key=${crypto.randomUUID()}`, options),
  sample: options => api.getBlob('/letterhead/sample-pdf', options),
};

export const priceIndexService = {
  view: options => api.get('/letter-templates/price-index', options),
  save: (payload, options) => api.put('/letter-templates/price-index', payload, options),
};

const MONTH_FORMS = [/^(\d{4})-(\d{1,2})$/, /^(\d{1,2})[./](\d{4})$/];

/** Lines like "2025-08;121,4", "08/2025 121,4" or "08.2025<Tab>121.4" → {"2025-08": "121.4"}; with the lines that could not be read. */
export function parsePriceIndex(text) {
  const values = {};
  const errors = [];
  String(text || '').split(/\r?\n/).forEach((line, index) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    const [rawMonth, rawValue, ...rest] = trimmed.split(/[;\t ]+/);
    let year; let month;
    for (const form of MONTH_FORMS) {
      const match = rawMonth?.match(form);
      if (match) { [year, month] = form === MONTH_FORMS[0] ? [match[1], match[2]] : [match[2], match[1]]; break; }
    }
    const value = (rawValue || '').replace(',', '.');
    if (!year || Number(month) < 1 || Number(month) > 12 || rest.length || !/^\d{1,4}(\.\d{1,3})?$/.test(value)) {
      errors.push(`Zeile ${index + 1}: „${trimmed}“`);
      return;
    }
    values[`${year}-${String(month).padStart(2, '0')}`] = value;
  });
  return { values, errors };
}

export const formatPriceIndex = values => Object.keys(values || {}).sort()
  .map(month => `${month};${String(values[month]).replace('.', ',')}`).join('\n');
