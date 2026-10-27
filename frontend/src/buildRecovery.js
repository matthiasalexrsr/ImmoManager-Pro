// After an update the server holds the new version's files only. A page opened before it
// can no longer fetch a part it loads later; Vite reports that as `vite:preloadError`.
// Loading the current page once fixes it. A second failure shortly after is a real fault:
// it is left to the error boundary instead of reloading in a loop.

export const RELOAD_KEY = 'immo-build-reload';
const RELOAD_WINDOW_MS = 60_000;

function sessionStore() {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function installBuildRecovery(target = window, storage = sessionStore(), now = Date.now) {
  const recover = event => {
    if (!storage) return;
    try {
      if (now() - (Number(storage.getItem(RELOAD_KEY)) || 0) < RELOAD_WINDOW_MS) return;
      storage.setItem(RELOAD_KEY, String(now()));
    } catch {
      return;
    }
    event.preventDefault();
    target.location.reload();
  };
  target.addEventListener('vite:preloadError', recover);
  return () => target.removeEventListener('vite:preloadError', recover);
}
