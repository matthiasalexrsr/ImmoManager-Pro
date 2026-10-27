import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import process from 'node:process';
import { JSDOM } from 'jsdom';
import { afterEach, expect, it, vi } from 'vitest';

const root = resolve(process.cwd(), '../mietvertrag_wizard_fastapi_reportlab_pro/mietvertrag_wizard');
const html = readFileSync(resolve(root, 'templates/mietvertrag_wizard/index.html'), 'utf8');
const script = readFileSync(resolve(root, 'static/mietvertrag_wizard/js/script.js'), 'utf8');
const key = 'mietvertragWizardFormState_v2';
const opened = [];
afterEach(() => { opened.splice(0).forEach(dom => dom.window.close()); });
async function wizard(embedded) {
  const dom = new JSDOM(html, { url: 'http://localhost/mietvertrag/', runScripts: 'outside-only' });
  opened.push(dom);
  const host = { postMessage: vi.fn() };
  if (embedded) Object.defineProperty(dom.window, 'parent', { value: host });
  dom.window.alert = vi.fn();
  dom.window.localStorage.setItem(key, JSON.stringify({ fields: { 'vermieter-name': { type: 'text', value: 'Fremder Browserstand' } } }));
  dom.window.eval(script);
  await new Promise(resolve => dom.window.document.addEventListener('DOMContentLoaded', resolve, { once: true }));
  return { dom, host, window: dom.window, document: dom.window.document };
}

it('isolates the embedded wizard from shared storage and serializes the actual restored form', async () => {
  const { window, document, host } = await wizard(true);
  const name = document.querySelector('[name="vermieter-name"]');
  expect(name.value).toBe('');
  expect(document.getElementById('btn-save-local').hidden).toBe(true);
  window.immoWizardDraft.restore({ fields: { 'vermieter-name': { type: 'text', value: 'Berechtigter Entwurf' } }, expertMode: true });
  expect(name.value).toBe('Berechtigter Entwurf');
  name.dispatchEvent(new window.Event('input', { bubbles: true }));
  expect(host.postMessage).toHaveBeenLastCalledWith(expect.objectContaining({ type: 'immo-wizard-draft',
    form: expect.objectContaining({ fields: expect.objectContaining({ 'vermieter-name': { type: 'text', value: 'Berechtigter Entwurf' } }), expertMode: true }) }), window.location.origin);
  expect(window.immoWizardDraft.serialize().fields).not.toHaveProperty('input-import-json');
  expect(JSON.parse(window.localStorage.getItem(key)).fields['vermieter-name'].value).toBe('Fremder Browserstand');
});

it('reports the completed asynchronous JSON import to the private host draft', async () => {
  const { window, document, host } = await wizard(true);
  window.FileReader = class {
    readAsText() { queueMicrotask(() => this.onload({ target: { result: JSON.stringify({ fields: {
      'vermieter-name': { type: 'text', value: 'Importierter Entwurf' },
    } }) } })); }
  };
  const input = document.getElementById('input-import-json');
  Object.defineProperty(input, 'files', { value: [new window.File(['{}'], 'draft.json')] });
  input.dispatchEvent(new window.Event('change', { bubbles: true }));
  await Promise.resolve();
  expect(host.postMessage.mock.calls.at(-1)[0].form.fields['vermieter-name'].value).toBe('Importierter Entwurf');
});

it('retains the standalone wizard manual storage behavior', async () => {
  const { window, document } = await wizard(false);
  const name = document.querySelector('[name="vermieter-name"]');
  expect(name.value).toBe('Fremder Browserstand');
  expect(window.immoWizardDraft).toBeUndefined();
  name.value = 'Standalone'; document.getElementById('btn-save-local').click();
  expect(JSON.parse(window.localStorage.getItem(key)).fields['vermieter-name'].value).toBe('Standalone');
});
