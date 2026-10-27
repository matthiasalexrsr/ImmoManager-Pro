let owner = null;
export const workspaceOwner = () => owner;
export function setWorkspaceOwner(id) {
  const next = id == null ? null : String(id);
  if (owner !== next) {
    owner = next;
    window.dispatchEvent(new CustomEvent('workspace-owner', { detail: next }));
  }
}
export const privateStorageKey = key => owner ? `workspace:${owner}:${key}` : key;
export function clearWorkspaceBrowserData() {
  for (const storage of [window.localStorage, window.sessionStorage]) {
    try {
      const keys = Array.from({ length: storage.length }, (_, i) => storage.key(i));
      keys.filter(key => key?.startsWith('workspace:')).forEach(key => storage.removeItem(key));
    } catch { /* Private browsing can disable storage. Server state remains authoritative. */ }
  }
  setWorkspaceOwner(null);
}
