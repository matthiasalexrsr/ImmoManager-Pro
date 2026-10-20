import { api } from '../../api';
import { sourceCommand } from '../documentWork/documentWorkApi';

const path = id => `/documents/${encodeURIComponent(id)}`;

export const documentDetailService = {
  load: (id, options) => api.get(`${path(id)}/details`, options),
  olderVersions: (id, before, options) => api.get(`${path(id)}/work/versions?${new URLSearchParams({ before: String(before), limit: '10' })}`, options),
  versionBlob: (id, versionId, options) => api.getBlob(`${path(id)}/work/versions/${encodeURIComponent(versionId)}/download`, options),
  source: (id, options) => api.get(`${path(id)}/work/source`, options),
  uploadVersion: (id, form) => api.upload(`${path(id)}/work/versions`, form),
  patch: (id, values) => api.patch(path(id), values),
  remove: id => api.del(path(id)),
};

const fileSignature = file => [file.name, file.size, file.lastModified].join('|');

/** Uploads `file` as the next version. A repeated attempt with the same file and comment (after
 *  a lost answer) reuses the command it was first sent with, so the server answers it as a replay
 *  instead of a conflict. `attempt` is a ref the caller keeps per document. */
export async function uploadNewVersion(service, id, file, comment, attempt) {
  const signature = fileSignature(file) + '|' + comment;
  if (attempt.current?.signature !== signature) {
    const source = await service.source(id);
    attempt.current = { signature, command: sourceCommand(source) };
  }
  const { command } = attempt.current;
  const form = new FormData();
  form.append('file', file);
  form.append('command_key', command.command_key);
  form.append('expected_sha256', command.expected_sha256);
  form.append('expected_document_revision', command.expected_document_revision);
  if (command.expected_version) form.append('expected_version', command.expected_version);
  form.append('comment', comment);
  const result = await service.uploadVersion(id, form);
  attempt.current = null;
  return result;
}

const OPERATIONS = { archive_original: 'Eingangsoriginal', upload: 'Neue Fassung', restore: 'Wiederhergestellt' };

export function versionLabel(version) {
  if (version.restored_from_id) return 'Wiederhergestellt';
  return OPERATIONS[version.operation] || 'Fassung';
}

/** The name a person gave the file, without the storage prefix of uploads ("<32 hex>_name.pdf"). */
export function shownFilename(name) {
  return String(name || '').replace(/^[0-9a-f]{32}_/, '') || 'Dokument';
}

export function sizeLabel(bytes) {
  if (!Number.isFinite(bytes)) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toLocaleString('de-DE', { maximumFractionDigits: 1 })} MB`;
}

export const TEXT_SOURCES = { pdf_text: 'Text der PDF-Datei', ocr: 'Texterkennung', office: 'Office-Datei', plain: 'Textdatei', none: 'kein lesbarer Text' };

/** What the preview can show: a PDF or an image of the current version, or nothing. */
export function previewKind(mediaType, name) {
  const type = (mediaType || '').toLowerCase();
  if (type === 'application/pdf' || /\.pdf$/i.test(name || '')) return 'pdf';
  if (/^image\/(png|jpe?g|gif|webp|bmp)$/.test(type) || /\.(png|jpe?g|gif|webp|bmp)$/i.test(name || '')) return 'image';
  return 'other';
}
