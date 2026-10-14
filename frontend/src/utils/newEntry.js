// "Neu" without the mouse: the global search's quick actions and Alt+N ask the current page for
// its New form. The first list on the page that may add answers (lists register in mount order).
export const NEW_ENTRY_EVENT = 'immo:new-entry';

// A request that arrived while the page was still loading its list (opened as /bookings?neu=1).
let pending = null;

/** Asks the page to open its New form; true when a list took it. */
export function requestNewEntry() {
  const event = new Event(NEW_ENTRY_EVENT, { cancelable: true });
  window.dispatchEvent(event);
  return event.defaultPrevented;
}

/** Keeps the request for the first list of this page that appears later. */
export function holdNewEntry(pathname) { pending = pathname; }

/** Forgets a held request once another page is shown. */
export function dropNewEntry(pathname) { if (pending !== pathname) pending = null; }

/** True once, for the first list that appears on the page the request was held for
 * (the shell drops the request as soon as another page is shown). */
export function takeNewEntry() {
  if (pending === null) return false;
  pending = null;
  return true;
}
