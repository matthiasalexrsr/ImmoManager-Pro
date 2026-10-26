// This client never reads internal tokens, preferences, portfolios or stores.
const BASE = '/api/v1/portal';
export async function portalRequest(path, { method = 'GET', body, signal, file = false } = {}) {
  const response = await fetch(BASE + path, { method, credentials: 'same-origin', signal, cache: 'no-store',
    headers: { 'X-Portal-Client': 'web-v1', ...(body instanceof FormData || body === undefined ? {} : { 'Content-Type': 'application/json' }) },
    body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body) });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const error = new Error(typeof data.detail === 'string' ? data.detail : data.error?.message || 'Die Portalaktion konnte nicht abgeschlossen werden.');
    error.status = response.status;
    if (response.status === 401 && path.startsWith('/me')) window.dispatchEvent(new Event('portal-session-lost'));
    throw error;
  }
  if (response.status === 204) return null;
  return file ? response.blob() : response.json();
}

export async function downloadPortal(path, filename) {
  const content = await portalRequest(path, { file: true });
  const url = URL.createObjectURL(content);
  const link = document.createElement('a');
  link.href = url; link.download = filename; document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function formCommand(command, files = []) {
  const form = new FormData();
  form.set('command', JSON.stringify(command));
  files.forEach(file => form.append('files', file));
  return form;
}
