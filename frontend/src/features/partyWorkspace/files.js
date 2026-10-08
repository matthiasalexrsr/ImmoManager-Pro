import { isOwnUploadUrl, prepareUploadAccess } from '../../utils/uploadAccess';

const API_BASE = import.meta.env.VITE_API_URL || '/api/v1';

/** File references are either our upload paths or ordinary HTTP(S) URLs. */
export function resolveFileUrl(value, apiBase = API_BASE) {
  if (typeof value !== 'string' || !value.trim()) return '';
  const raw = value.trim();
  if ([...raw].some(character => character.charCodeAt(0) < 32 || character === '\\') || raw.startsWith('//')) return '';
  try {
    const decoded = decodeURIComponent(raw.split(/[?#]/)[0]);
    if (decoded.split('/').some(part => part === '..' || part === '.')) return '';
    let url;
    if (/^https?:\/\//i.test(raw)) {
      url = new URL(raw);
    } else if (raw.startsWith('/uploads/') || raw.startsWith('uploads/')) {
      const origin = new URL(apiBase, window.location.origin).origin;
      url = new URL(raw.startsWith('/') ? raw : `/${raw}`, origin);
    } else {
      return '';
    }
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return '';
    return url.href;
  } catch {
    return '';
  }
}

export function fileKind(value) {
  const url = resolveFileUrl(value);
  if (!url) return 'other';
  const path = new URL(url).pathname;
  if (/\.pdf$/i.test(path)) return 'pdf';
  if (/\.(png|jpe?g|gif|bmp|tiff?|webp)$/i.test(path)) return 'image';
  return 'other';
}

/** Fetch a blob so Download also works for cross-origin storage URLs. */
export async function downloadFile(value, filename, { signal } = {}) {
  const url = resolveFileUrl(value);
  if (!url) throw new Error('Die Dateiadresse ist ungültig.');
  await prepareUploadAccess(url, { signal });
  const response = await fetch(url, { signal, credentials: isOwnUploadUrl(url) ? 'include' : 'same-origin' });
  if (!response.ok) throw new Error(`Download fehlgeschlagen (${response.status})`);
  const blob = await response.blob();
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  const original = decodeURIComponent(new URL(url).pathname.split('/').pop() || 'Dokument');
  const extension = /\.[a-z0-9]{1,8}$/i.exec(original)?.[0] || '';
  const label = [...(filename || original)].map(character => character.charCodeAt(0) < 32 || '<>:"/\\|?*'.includes(character) ? '_' : character).join('');
  anchor.href = objectUrl;
  anchor.download = extension && !label.toLowerCase().endsWith(extension.toLowerCase()) ? `${label}${extension}` : label;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // Give the browser time to begin reading the blob before revoking it.
  setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}
