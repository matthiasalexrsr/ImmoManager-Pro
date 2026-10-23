export const ENTITY_SHELF_CHANGED = 'immo:entity-shelf-changed';
export function notifyEntityShelf() { window.dispatchEvent(new Event(ENTITY_SHELF_CHANGED)); }
