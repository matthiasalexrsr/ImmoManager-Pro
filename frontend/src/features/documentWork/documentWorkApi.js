import { api } from '../../api';

export function sourceCommand(source) {
  return { expected_version: source.version?.id || null, expected_sha256: source.sha256,
    expected_document_revision: source.document_revision, command_key: crypto.randomUUID() };
}

export async function blobBase64(blob) {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let result = '';
  for (let index = 0; index < bytes.length; index += 16384) {
    result += String.fromCharCode(...bytes.subarray(index, index + 16384));
  }
  return btoa(result);
}

export function base64Blob(value, type) {
  return new Blob([Uint8Array.from(atob(value), char => char.charCodeAt(0))], { type });
}

export async function downloadVersion(documentId, versionId, name) {
  const current = api.captureSession();
  const blob = await api.getBlob(`/documents/${encodeURIComponent(documentId)}/work/versions/${encodeURIComponent(versionId)}/download`);
  current();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function pageNumbers(value) {
  const result = [];
  for (const part of value.split(',').map(item => item.trim()).filter(Boolean)) {
    if (!/^\d+(-\d+)?$/.test(part)) throw new Error('Seiten bitte als 1,3,5-8 angeben.');
    const [start, end = start] = part.split('-').map(Number);
    if (start < 1 || end < start || end - start > 10000) throw new Error('Ungültiger Seitenbereich.');
    for (let number = start; number <= end; number += 1) result.push(number - 1);
  }
  if (!result.length) throw new Error('Bitte mindestens eine Seite angeben.');
  return result;
}
