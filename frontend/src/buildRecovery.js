// After an update the server holds the new version's files only. A page opened before it
// can no longer fetch a part it loads later. When a lazily loaded part fails and the server
// now names a different entry file, the page loads the current version once and keeps its
// loading state until then. A failure while the page is being left (a navigation aborts the
// fetch) is no error at all. Any other failure is a real fault for the error boundary; so is
// a second one shortly after a reload, instead of reloading in a loop.
import { lazy } from 'react';

export const RELOAD_KEY = 'immo-build-reload';
const RELOAD_WINDOW_MS = 60_000;
const ENTRY = /<script\b[^>]*\bsrc="([^"]*\/assets\/[^"]+\.js)"/;

let leaving = false;
if (typeof window !== 'undefined') {
  const leave = () => { leaving = true; };
  window.addEventListener('beforeunload', leave);
  window.addEventListener('pagehide', leave);
  window.addEventListener('pageshow', () => { leaving = false; });
}

function sessionStore() {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

const pending = () => new Promise(() => {});

export function currentEntry(doc = document) {
  return [...doc.querySelectorAll('script[type="module"][src]')]
    .map(script => script.getAttribute('src'))
    .find(src => src.includes('/assets/')) || null;
}

export async function recoverFromMissingPart(error, {
  fetchPage = () => fetch('/', { cache: 'no-store', credentials: 'same-origin' }).then(response => response.text()),
  entry = currentEntry(),
  location = window.location,
  storage = sessionStore(),
  now = Date.now,
  isLeaving = () => leaving,
} = {}) {
  if (isLeaving()) return pending();
  let served = null;
  try {
    served = (await fetchPage()).match(ENTRY)?.[1] || null;
  } catch {
    throw error;
  }
  if (!entry || !served || served === entry || !storage) throw error;
  try {
    if (now() - (Number(storage.getItem(RELOAD_KEY)) || 0) < RELOAD_WINDOW_MS) throw error;
    storage.setItem(RELOAD_KEY, String(now()));
  } catch {
    throw error;
  }
  location.reload();
  return pending();
}

// React.lazy for the program's pages, with the recovery above.
export function lazyWithRecovery(loader) {
  return lazy(() => loader().catch(error => recoverFromMissingPart(error)));
}
