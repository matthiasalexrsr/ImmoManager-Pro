import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';

export function storageKey(reference) {
  if (typeof reference !== 'string' || !reference.trim()) return '';
  let value = reference.trim();
  let s3 = false;
  try {
    if (/^s3:\/\//i.test(value)) {
      const remote = new URL(value);
      if (!remote.hostname || remote.username || remote.password || remote.search || remote.hash) throw new Error();
      s3 = true;
      value = remote.pathname;
    } else if (/^https?:\/\//i.test(value)) {
      const remote = new URL(value);
      if (remote.origin !== window.location.origin || !remote.pathname.startsWith('/uploads/')) throw new Error();
      value = remote.pathname;
    } else if (/^[a-z][a-z\d+.-]*:/i.test(value) || value.startsWith('//')) {
      throw new Error();
    }
    value = decodeURIComponent(value);
    if (!s3) value = value.replace(/^\/?uploads\//, '');
    value = value.replace(/^\//, '');
    if (!value || /[\\?#]/.test(value) || [...value].some(char => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127) || value.split('/').some(part => !part || part === '.' || part === '..') || /^[a-z]:/i.test(value)) throw new Error();
    return value;
  } catch {
    throw new Error('Ungültiger Dateiverweis. Bitte verwenden Sie eine Datei dieser Installation.');
  }
}

export function previewKind(key) {
  if (/\.(png|jpe?g|gif|webp)$/i.test(key)) return 'image';
  if (/\.pdf$/i.test(key)) return 'pdf';
  return 'download';
}

function headerBytes(blob, signal) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    const abort = () => reader.abort();
    signal.addEventListener('abort', abort, { once: true });
    const complete = action => value => { signal.removeEventListener('abort', abort); action(value); };
    reader.onload = complete(() => resolve(new Uint8Array(reader.result)));
    reader.onerror = complete(() => reject(new Error('Datei konnte nicht gelesen werden.')));
    reader.onabort = complete(() => reject(new DOMException('Abgebrochen', 'AbortError')));
    reader.readAsArrayBuffer(blob.slice(0, 32));
  });
}

function verifiedType(key, bytes) {
  const ascii = String.fromCharCode(...bytes);
  if (/\.pdf$/i.test(key) && /^%PDF-[12]\.\d/.test(ascii)) return 'application/pdf';
  if (/\.png$/i.test(key) && [137, 80, 78, 71, 13, 10, 26, 10].every((byte, index) => bytes[index] === byte)) return 'image/png';
  if (/\.jpe?g$/i.test(key) && bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255) return 'image/jpeg';
  if (/\.gif$/i.test(key) && /^GIF8[79]a/.test(ascii)) return 'image/gif';
  if (/\.webp$/i.test(key) && ascii.startsWith('RIFF') && ascii.slice(8, 12) === 'WEBP') return 'image/webp';
  return null;
}

export default function useProtectedFile(reference) {
  const [state, setState] = useState({ reference: null, url: '', key: '', kind: 'download', error: null, loading: false });
  const [revision, setRevision] = useState(0);
  const retry = useCallback(() => setRevision(value => value + 1), []);
  useEffect(() => {
    const controller = new AbortController();
    let objectUrl;
    setState({ reference, url: '', key: '', kind: 'download', error: null, loading: !!reference });
    if (reference) {
      (async () => {
        try {
          const key = storageKey(reference);
          const blob = await api.getBlob(`/files/download?key=${encodeURIComponent(key)}`, { signal: controller.signal });
          if (controller.signal.aborted) return;
          const expected = previewKind(key);
          // Only verified PDF/raster bytes enter a preview; HTML, SVG and unknown
          // files remain octet-stream downloads, regardless of declared MIME.
          const safeType = expected === 'download' ? null : verifiedType(key, await headerBytes(blob, controller.signal));
          if (controller.signal.aborted) return;
          const type = safeType || 'application/octet-stream';
          objectUrl = URL.createObjectURL(type === blob.type ? blob : new Blob([blob], { type }));
          setState({ reference, url: objectUrl, key, kind: safeType ? expected : 'download', previewError: expected !== 'download' && !safeType ? 'Dateiinhalt passt nicht zum Dateityp. Die Datei kann nur heruntergeladen werden.' : null, error: null, loading: false });
        } catch (error) {
          if (!controller.signal.aborted) setState({ reference, url: '', key: '', kind: 'download', error: error.message, loading: false });
        }
      })();
    }
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [reference, revision]);
  // Hide an old file immediately when the caller changes reference.
  return { ...(state.reference === reference ? state : { url: '', key: '', error: null, loading: !!reference }), retry };
}
