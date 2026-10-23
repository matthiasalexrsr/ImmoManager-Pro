// The editor is an optional local installation served from this application's
// origin. Keep loading separate from the editor's session/navigation lifecycle.
export function loadDocumentEditor() {
  const moduleUrl = '/document-editor/editor.js';
  return import(/* @vite-ignore */ moduleUrl);
}
