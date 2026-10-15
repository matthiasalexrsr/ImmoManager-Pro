// "Neu" without the mouse: the global search's quick actions and Alt+N ask the current page for
// its New form. The first list on the page that may add answers (lists register in mount order).
export const NEW_ENTRY_EVENT = 'immo:new-entry';

// A request that arrived while the page was still loading its list (opened as /bookings?neu=1).
// `prefill` are values the New form starts with (the property a unit is added to).
let pending = null;

/** Asks the page to open its New form; true when a list took it. */
export function requestNewEntry(prefill) {
  const event = new CustomEvent(NEW_ENTRY_EVENT, { cancelable: true, detail: prefill || null });
  window.dispatchEvent(event);
  return event.defaultPrevented;
}

/** Keeps the request for the first list of this page that appears later. */
export function holdNewEntry(pathname, prefill) { pending = { pathname, prefill: prefill || null }; }

/** Forgets a held request once another page is shown. */
export function dropNewEntry(pathname) { if (pending?.pathname !== pathname) pending = null; }

/** Once, for the first list that appears on the page the request was held for (the shell drops the
 * request as soon as another page is shown): `{ prefill }`, else null. */
export function takeNewEntry() {
  if (pending === null) return null;
  const taken = { prefill: pending.prefill };
  pending = null;
  return taken;
}

/** Where a link opens a list's New form with these values: `<Link to={to} state={state}>`. */
export function newEntryLink(path, prefill) {
  return { to: `${path}?neu=1`, state: prefill ? { prefill } : undefined };
}
