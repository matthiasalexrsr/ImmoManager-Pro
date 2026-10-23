/** Same-origin SPA paths. Reject browser URL syntax that can escape an app link. */
export function safeInternalHref(value) {
  return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//')
    && !value.includes('\\') && ![...value].some(character => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127) ? value : '';
}
