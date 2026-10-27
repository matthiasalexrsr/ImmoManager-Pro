// Optional separately built component. SuperDoc's AGPL/commercial license applies
// to that dependency. Inclusion does not automatically resolve application licensing.
import { SuperDoc } from 'superdoc';
import 'superdoc/style.css';

export function mountEditor(element, file, { onReady, onError }) {
  // Vanilla v2 does not create a toolbar mount (the React wrapper does).
  // Keep mounts owned by this instance so reopening another session is safe.
  const toolbar = document.createElement('div');
  toolbar.id = `document-toolbar-${crypto.randomUUID()}`;
  toolbar.setAttribute('aria-label', 'Dokument formatieren und prüfen');
  toolbar.style.cssText = 'width:100%;min-height:42px;position:relative;z-index:2;';
  const canvas = document.createElement('div');
  canvas.style.height = '70vh';
  canvas.style.position = 'relative';
  canvas.style.zIndex = '1';
  element.replaceChildren(toolbar, canvas);
  const editor = new SuperDoc({ selector: canvas, document: file, documentMode: 'editing', contained: true,
    telemetry: { enabled: false },
    ui: { toolbar: { container: `#${toolbar.id}`, responsiveTo: 'container', items: {
      left: ['undo', 'redo'],
      center: ['font-family', 'font-size', 'bold', 'italic', 'underline', 'text-color', 'highlight-color',
        'linked-style', 'text-align', 'bullet-list', 'numbered-list', 'indent-decrease', 'indent-increase',
        'link', 'image', 'table', 'table-actions', 'page-number', 'table-of-contents',
        'track-changes-accept-selection', 'track-changes-reject-selection'],
      right: ['search', 'document-mode', 'zoom'],
    } } },
    // Embed local images in the native DOCX. No upload service or remote URL.
    handleImageUpload: file => new Promise((resolve, reject) => {
      if (!/^image\/(png|jpe?g)$/i.test(file.type)) {
        reject(new Error('Bitte ein PNG- oder JPEG-Bild auswählen.')); return;
      }
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(reader.error || new Error('Das Bild konnte nicht gelesen werden.'));
      reader.readAsDataURL(file);
    }),
    onReady, onContentError: ({ error }) => onError(error), onException: ({ error }) => onError(error) });
  return { exportDocx: () => editor.export({ triggerDownload: false }),
    suggesting: value => editor.setDocumentMode(value ? 'suggesting' : 'editing'),
    destroy: () => { editor.destroy(); element.replaceChildren(); } };
}
