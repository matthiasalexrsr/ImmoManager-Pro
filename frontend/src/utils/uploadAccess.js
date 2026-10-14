import { api } from '../api';

const API_BASE = import.meta.env.VITE_API_URL || '/api/v1';
let pending = null;
const aborted = () => new DOMException('Aborted', 'AbortError');

export function isOwnUploadUrl(value) {
  try {
    const url = new URL(value, window.location.origin);
    return ['http:', 'https:'].includes(url.protocol)
      && url.origin === new URL(API_BASE, window.location.origin).origin
      && url.pathname.startsWith('/uploads/');
  } catch { return false; }
}

function joinPreparation(token, signal) {
  if (signal?.aborted) return Promise.reject(aborted());
  if (!pending || pending.token !== token || pending.controller.signal.aborted) {
    const entry = { token, controller: new AbortController(), users: 0, settled: false };
    pending = entry;
    entry.promise = api.get('/auth/me', { signal: entry.controller.signal }).finally(() => {
      entry.settled = true;
      if (pending === entry) pending = null;
    });
  }
  const entry = pending;
  entry.users += 1;
  return new Promise((resolve, reject) => {
    let finished = false;
    const finish = (action, value) => {
      if (finished) return;
      finished = true;
      signal?.removeEventListener('abort', onAbort);
      entry.users -= 1;
      if (!entry.users && !entry.settled) entry.controller.abort();
      action(value);
    };
    const onAbort = () => finish(reject, aborted());
    signal?.addEventListener('abort', onAbort, { once: true });
    entry.promise.then(value => finish(resolve, value), error => finish(reject, error));
  });
}

/** Only active calls share a check; no successful authorization survives a later action/logout. */
export async function prepareUploadAccess(url, { signal } = {}) {
  if (signal?.aborted) throw aborted();
  if (!isOwnUploadUrl(url)) return;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const token = localStorage.getItem('access_token');
    await joinPreparation(token, signal);
    if (signal?.aborted) throw aborted();
    const current = localStorage.getItem('access_token');
    if (current === token) return;
    if (!current) break;
    // The API may have renewed the token: ensure the cookie belongs to that session.
  }
  throw new Error('Die Anmeldung hat sich geändert. Bitte öffnen Sie die Datei erneut.');
}
