import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';

/** Explicit product assets: old optional builds in public/ never enter the core edition. */
export default function productAssets() {
  let root;
  return {
    name: 'explicit-product-assets',
    apply: 'build',
    config: () => ({ publicDir: false }),
    configResolved: config => { root = config.root; },
    generateBundle() {
      const emitDirectory = (directory, prefix = '') => {
        if (!existsSync(directory)) return;
        for (const entry of readdirSync(directory, { withFileTypes: true })) {
          if (!prefix && entry.name === 'document-editor') continue;
          const name = prefix + entry.name;
          if (entry.isDirectory()) emitDirectory(join(directory, entry.name), name + '/');
          else if (entry.isFile()) this.emitFile({type:'asset', fileName:name, source:readFileSync(join(directory, entry.name))});
          else throw new Error(`Unsupported public asset: ${name}`);
        }
      };
      emitDirectory(resolve(root, 'public'));
      if (process.env.IMMO_BUILD_DOCUMENT_TOOLS === '1') {
        if (!['validation', 'licensed'].includes(process.env.IMMO_BUILD_PURPOSE)) {
          throw new Error('Document tools require an explicit validation or licensed build purpose. See docs/COMMERCIAL_RELEASE.md.');
        }
        const editor = resolve(root, '../artifacts/document-editor');
        if (!existsSync(join(editor, 'editor.js'))) throw new Error('Build the optional editor first.');
        if (process.env.IMMO_BUILD_PURPOSE === 'licensed') {
          const approval = JSON.parse(readFileSync(process.env.IMMO_LICENSE_APPROVAL_FILE || '', 'utf8'));
          for (const name of ['superdoc', '@superdoc/docx-engine', 'PyMuPDF']) {
            const entry = approval.components?.[name];
            if (!entry?.reference || entry.distribution !== true) throw new Error(`Missing distribution rights record for ${name}`);
          }
        }
        emitDirectory(editor, 'document-editor/');
      }
      this.emitFile({type:'asset', fileName:'product-profile.json', source:JSON.stringify({
        document_tools: process.env.IMMO_BUILD_DOCUMENT_TOOLS === '1',
        purpose: process.env.IMMO_BUILD_PURPOSE || 'core',
      }, null, 2)});
    },
  };
}
