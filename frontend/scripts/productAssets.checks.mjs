import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, sep } from 'node:path';
import productAssets from './productAssets.mjs';

function fixture(run) {
  const prefix = resolve(tmpdir()) + sep + 'immo-assets-';
  const folder = mkdtempSync(prefix);
  const saved = { ...process.env };
  try {
    delete process.env.IMMO_BUILD_DOCUMENT_TOOLS;
    delete process.env.IMMO_BUILD_PURPOSE;
    delete process.env.IMMO_LICENSE_APPROVAL_FILE;
    const root = join(folder, 'frontend');
    mkdirSync(join(root, 'public/document-editor'), {recursive:true});
    writeFileSync(join(root, 'public/health.txt'), 'core asset');
    writeFileSync(join(root, 'public/document-editor/editor.js'), 'STALE OPTIONAL BUILD');
    mkdirSync(join(folder,'artifacts/document-editor'), {recursive:true});
    writeFileSync(join(folder,'artifacts/document-editor/editor.js'), 'NEW OPTIONAL BUILD');
    const build = () => {
      const plugin = productAssets(), files = new Map();
      assert.equal(plugin.config().publicDir, false);
      plugin.configResolved({root});
      plugin.generateBundle.call({emitFile: asset => files.set(asset.fileName, asset.source)});
      return files;
    };
    run({folder,build});
  } finally {
    for (const key of Object.keys(process.env)) if (!(key in saved)) delete process.env[key];
    Object.assign(process.env,saved);
    if (!resolve(folder).startsWith(prefix)) throw Error('Refuse cleanup outside owned fixture');
    rmSync(folder,{recursive:true,force:true});
  }
}
test('core build never copies stale optional assets from public',()=>fixture(({build})=>{
  const files=build();
  assert.equal(files.get('health.txt').toString(),'core asset');
  assert.ok(![...files.keys()].some(name=>name.startsWith('document-editor/')));
  assert.deepEqual(JSON.parse(files.get('product-profile.json')), {document_tools:false,purpose:'core'});
}));
test('optional assets require an explicit build purpose',()=>fixture(({build})=>{
  process.env.IMMO_BUILD_DOCUMENT_TOOLS='1';
  assert.throws(build,/explicit validation or licensed/);
}));
test('validation uses freshly built optional assets and carries its purpose',()=>fixture(({build})=>{
  process.env.IMMO_BUILD_DOCUMENT_TOOLS='1'; process.env.IMMO_BUILD_PURPOSE='validation';
  const files=build();
  assert.equal(files.get('document-editor/editor.js').toString(),'NEW OPTIONAL BUILD');
  assert.equal(JSON.parse(files.get('product-profile.json')).purpose,'validation');
}));
test('customer profile requires rights for every document component',()=>fixture(({folder,build})=>{
  process.env.IMMO_BUILD_DOCUMENT_TOOLS='1'; process.env.IMMO_BUILD_PURPOSE='licensed';
  const approval=join(folder,'approval.json'); process.env.IMMO_LICENSE_APPROVAL_FILE=approval;
  for(const missing of ['superdoc','@superdoc/docx-engine','PyMuPDF']){
    const components=Object.fromEntries(['superdoc','@superdoc/docx-engine','PyMuPDF'].map(name=>[name,{reference:'synthetic test only',distribution:true}]));
    delete components[missing]; writeFileSync(approval,JSON.stringify({components}));
    assert.throws(build,/Missing distribution rights record/);
  }
}));
