import { api } from '../../api';
import { resolveFileUrl } from '../partyWorkspace/files';
import { isOwnUploadUrl, prepareUploadAccess } from '../../utils/uploadAccess';

const base = id => `/documents/${encodeURIComponent(id)}`;

/** The name in Content-Disposition (filename*=UTF-8''…), else the fallback. */
export function filenameOf(headers, fallback) {
  const value = headers?.get?.('Content-Disposition') || '';
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(value)?.[1];
  if (encoded) {
    try { return decodeURIComponent(encoded); } catch { /* the fallback below */ }
  }
  return fallback;
}

/** The document's current file (newest archived version, else the upload) as a File. */
export async function currentFile(id, title, { signal } = {}) {
  const { blob, headers } = await api.getFile(`${base(id)}/file`, { signal });
  return new File([blob], filenameOf(headers, title || 'Dokument'), { type: blob.type || 'application/octet-stream' });
}

export function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

let printFrame = null;

/** Opens the browser's print dialog for a PDF without leaving the page. */
export function printPdf(blob) {
  printFrame?.remove();
  const url = URL.createObjectURL(blob);
  const frame = document.createElement('iframe');
  frame.title = 'Druckansicht';
  frame.setAttribute('aria-hidden', 'true');
  frame.tabIndex = -1;
  // not display:none – the PDF viewer would not load and the page would print empty
  Object.assign(frame.style, { position: 'fixed', right: '0', bottom: '0', width: '1px', height: '1px', border: '0', opacity: '0' });
  frame.addEventListener('load', () => {
    // the viewer needs a moment after loading before it prints every page
    setTimeout(() => {
      try {
        frame.contentWindow.focus();
        frame.contentWindow.print();
      } catch {
        window.open(url, '_blank', 'noopener');   // the browser prints from its own PDF tab then
      }
    }, 250);
  }, { once: true });
  frame.src = url;
  document.body.appendChild(frame);
  printFrame = frame;
  // the file stays for the dialog; it goes with the next print job or after ten minutes
  setTimeout(() => { URL.revokeObjectURL(url); if (printFrame === frame) { frame.remove(); printFrame = null; } }, 600000);
}

/** Prints an image on its own page (scaled to the paper, without the page around it). */
export function printImage(blob) {
  printFrame?.remove();
  const url = URL.createObjectURL(blob);
  const frame = document.createElement('iframe');
  frame.title = 'Druckansicht';
  frame.setAttribute('aria-hidden', 'true');
  frame.tabIndex = -1;
  Object.assign(frame.style, { position: 'fixed', right: '0', bottom: '0', width: '1px', height: '1px', border: '0', opacity: '0' });
  frame.srcdoc = `<!doctype html><html><head><style>@page{margin:10mm}html,body{margin:0;height:100%}`
    + `body{display:flex;align-items:center;justify-content:center}img{max-width:100%;max-height:100%;object-fit:contain}</style>`
    + `</head><body><img src="${url}" alt=""></body></html>`;
  frame.addEventListener('load', () => {
    const image = frame.contentDocument?.querySelector('img');
    const go = () => { frame.contentWindow.focus(); frame.contentWindow.print(); };
    if (!image || image.complete) go(); else image.addEventListener('load', go, { once: true });
  }, { once: true });
  document.body.appendChild(frame);
  printFrame = frame;
  setTimeout(() => { URL.revokeObjectURL(url); if (printFrame === frame) { frame.remove(); printFrame = null; } }, 600000);
}

/** Prints a stored file (an upload or another web address): PDFs and images; other formats say so. */
export async function printFileUrl(value, { signal } = {}) {
  const url = resolveFileUrl(value);
  if (!url) throw new Error('Die Dateiadresse ist ungültig.');
  await prepareUploadAccess(url, { signal });
  const response = await fetch(url, { signal, credentials: isOwnUploadUrl(url) ? 'include' : 'same-origin' });
  if (!response.ok) throw new Error(`Die Datei konnte nicht geladen werden (${response.status}).`);
  const blob = await response.blob();
  const path = new URL(url).pathname;
  if (blob.type === 'application/pdf' || /\.pdf$/i.test(path)) return printPdf(new Blob([blob], { type: 'application/pdf' }));
  if (blob.type.startsWith('image/') || /\.(png|jpe?g|gif|bmp|webp)$/i.test(path)) return printImage(blob);
  throw new Error('Für dieses Dateiformat gibt es keine Druckansicht. Bitte herunterladen und im passenden Programm drucken.');
}

/** Prints one or several documents as one PDF; returns the ones left out ({ title, reason }). */
export async function printDocuments(ids, { signal, print = printPdf } = {}) {
  const { blob, headers } = await api.postFile('/documents/print', { ids }, { signal });
  let skipped = [];
  try { skipped = JSON.parse(decodeURIComponent(headers.get('X-Print-Skipped') || '[]')); } catch { skipped = []; }
  print(blob);
  return { skipped: Array.isArray(skipped) ? skipped : [] };
}

export function skippedNote(skipped) {
  if (!skipped?.length) return '';
  return `Nicht gedruckt: ${skipped.map(item => `„${item.title}“ (${item.reason})`).join(', ')}.`;
}

/** An unsent e-mail with the file attached; opened from the download it is a ready draft. */
export async function emailDraft(id, { to = [], cc = [], subject = '', body = '' }, { signal } = {}) {
  const { blob, headers } = await api.postFile(`${base(id)}/email-draft`, { to, cc, subject, body }, { signal });
  saveBlob(blob, filenameOf(headers, 'Entwurf.eml'));
}

/** International digits for wa.me ("0170 123 45 67" -> "491701234567"), or '' when it is no phone number. */
export function whatsAppNumber(phone, country = '49') {
  let digits = String(phone || '').trim();
  if (!digits) return '';
  const international = digits.startsWith('+') || digits.startsWith('00');
  digits = digits.replace(/\(0\)/g, '').replace(/\D/g, '');
  if (digits.startsWith('00')) digits = digits.slice(2);
  else if (!international && digits.startsWith('0')) digits = country + digits.slice(1);
  return /^[1-9]\d{7,14}$/.test(digits) ? digits : '';
}

export function whatsAppLink(phone, text) {
  const number = whatsAppNumber(phone);
  const query = text ? `?text=${encodeURIComponent(text)}` : '';
  return `https://wa.me/${number}${query}`;
}

/** Whether the system share dialog (Windows: WhatsApp, Mail, Outlook, Teams, Nearby Sharing …) takes files. */
export function canShareFiles() {
  try {
    if (typeof navigator === 'undefined' || typeof navigator.share !== 'function' || typeof navigator.canShare !== 'function') return false;
    return navigator.canShare({ files: [new File(['x'], 'probe.pdf', { type: 'application/pdf' })] });
  } catch {
    return false;
  }
}
