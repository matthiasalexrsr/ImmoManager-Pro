import { api } from '../../api';

export const LETTER_FIELDS = ['sender_name', 'sender_address', 'recipient_name', 'recipient_address', 'issue_date', 'subject', 'salutation', 'intro', 'closing', 'signature'];
export const REQUIRED_LETTER_FIELDS = LETTER_FIELDS.slice(0, 7);
export const letterData = values => Object.fromEntries(LETTER_FIELDS.map(key => [key, String(values?.[key] ?? '').trim()]));
export const letterSignature = values => JSON.stringify(letterData(values));
const root = id => `/billing/statements/${encodeURIComponent(id)}`;
const HASH = /^[a-f0-9]{64}$/;

export function checkLetterPreview(preview, payload) {
  if (!HASH.test(preview?.review_hash || '') || !HASH.test(preview?.pdf_sha256 || '')
    || preview?.state !== 'preview' || preview?.review?.source_revision !== payload.source_revision
    || letterSignature(preview?.review?.data) !== letterSignature(payload.data)
    || preview?.review?.pdf_sha256 !== preview.pdf_sha256 || typeof preview.review.draft !== 'boolean') {
    throw new Error('Die Vorschau passt nicht zum aktuellen Brief. Bitte erneut erstellen.');
  }
  return preview;
}

export async function letterPdfHash(blob) {
  const bytes = await blob.arrayBuffer();
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, '0')).join('');
}

// Only authenticated, same-origin API downloads are accepted. Never put a
// session token into a URL or follow an arbitrary URL from a record.
export function letterDownloadPath(value) {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//') || value.includes('\\')) throw new Error('Die Downloadadresse ist ungültig.');
  const url = new URL(value, window.location.origin);
  if (url.origin !== window.location.origin || url.hash || [...url.searchParams.keys()].some(key => /token|authorization/i.test(key))) throw new Error('Die Downloadadresse ist ungültig.');
  const path = url.pathname.replace(/^\/api\/v1(?=\/)/, '');
  if (!path.startsWith('/billing/') && !path.startsWith('/documents/') && !path.startsWith('/files/')) throw new Error('Die Downloadadresse ist ungültig.');
  return path + url.search;
}

export const statementLetterService = {
  loadContext: (id, options) => api.get(`${root(id)}/letter-context`, options),
  preview: (id, payload, options) => api.post(`${root(id)}/letter-preview`, payload, options),
  previewPdf: (id, payload, options) => api.postBlob(`${root(id)}/letter-preview-pdf`, payload, options),
  publish: (id, payload, options) => api.post(`${root(id)}/letter-publish`, payload, options),
  downloadOriginal: (record, options) => api.getBlob(letterDownloadPath(record.download_url), options),
};
