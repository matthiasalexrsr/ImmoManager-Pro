import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath, URL } from 'node:url';
import { generateInventory, validateInventory } from './frontendSbom.mjs';

function fixture() {
  const manifest = { name: 'frontend', version: '0.0.0', dependencies: { react: '^19', 'react-dom': '^19' }, devDependencies: { tool: '^1' } };
  const lock = { lockfileVersion: 3, packages: { '': JSON.parse(JSON.stringify(manifest)),
    'node_modules/react': { version: '19.2.4' }, 'node_modules/react-dom': { version: '19.2.4', dependencies: { scheduler: '^0.27' }, peerDependencies: { react: '^19' } },
    'node_modules/react-dom/node_modules/scheduler': { version: '0.27.0' }, 'node_modules/tool': { version: '1.0.0' } } };
  const refs = ['react@19.2.4', 'react-dom@19.2.4', 'scheduler@0.27.0', 'tool@1.0.0'];
  const bom = { bomFormat: 'CycloneDX', metadata: { component: { name: 'frontend', version: '0.0.0', 'bom-ref': 'frontend@0.0.0' } },
    components: refs.map(ref => { const split = ref.lastIndexOf('@'); return { 'bom-ref': ref, name: ref.slice(0, split), version: ref.slice(split + 1) }; }),
    dependencies: [{ ref: 'frontend@0.0.0', dependsOn: [refs[0], refs[1], refs[3]] },
      ...refs.map(ref => ({ ref, dependsOn: ref === refs[1] ? [refs[0], refs[2]] : [] }))] };
  return { bom, manifest, lock };
}
const check = ({ bom, manifest, lock }) => validateInventory(bom, manifest, lock);
test('validates the full inventory and production-root transitive closure', () => {
  const result = check(fixture());
  assert.equal(result.components, 4); assert.equal(result.root_dependencies, 3);
  assert.deepEqual(result.production_closure_components, ['react-dom@19.2.4', 'react@19.2.4', 'scheduler@0.27.0']);
});
test('refuses an otherwise coherent inventory which omits React', () => {
  const data = fixture(), ref = 'react@19.2.4';
  data.bom.components = data.bom.components.filter(item => item['bom-ref'] !== ref);
  data.bom.dependencies = data.bom.dependencies.filter(item => item.ref !== ref).map(item => ({ ...item, dependsOn: item.dependsOn.filter(target => target !== ref) }));
  assert.throws(() => check(data), /Missing locked components/);
});
test('refuses incorrect versions, dangling refs, duplicates and missing transitive edges', () => {
  for (const mutate of [data => { data.bom.components[0].version = '19.2.5'; },
    data => data.bom.dependencies[0].dependsOn.push('missing@1'), data => data.bom.components.push(data.bom.components[0]),
    data => data.bom.dependencies.push(data.bom.dependencies[0]), data => { data.bom.dependencies[2].dependsOn = ['react@19.2.4']; }]) {
    const data = fixture(); mutate(data); assert.throws(() => check(data));
  }
});
test('refuses malformed input and manifest/lock drift', () => {
  const data = fixture(); assert.throws(() => validateInventory(null, data.manifest, data.lock), /Malformed/);
  data.manifest.dependencies.react = '^20'; assert.throws(() => check(data), /package.json\/lock/);
  const changed = fixture(); changed.lock.packages['node_modules/react'].version = '20.0.0'; assert.throws(() => check(changed), /component\/version/);
});
test('generates and validates the actual complete lock offline, including platform optionals', () => {
  const root = fileURLToPath(new URL('..', import.meta.url)), { bom, report } = generateInventory(root);
  const lock = JSON.parse(readFileSync(new URL('../package-lock.json', import.meta.url)));
  const manifest = JSON.parse(readFileSync(new URL('../package.json', import.meta.url)));
  assert.equal(report.lock_locations, Object.keys(lock.packages).length - 1);
  assert.equal(report.production_direct_dependencies.length, Object.keys(manifest.dependencies).length);
  assert.equal(report.root_dependencies, Object.keys({ ...manifest.dependencies, ...manifest.devDependencies, ...manifest.optionalDependencies }).length);
  assert.equal(bom.metadata.component['bom-ref'], `${manifest.name}@${manifest.version}`);
  const identities = Object.entries(lock.packages).filter(([path]) => path).map(([path, item]) => `${item.name || path.split('node_modules/').at(-1)}@${item.version}`);
  assert.equal(report.components, new Set(identities).size);
  const dom = bom.dependencies.find(item => item.ref === `react-dom@${lock.packages['node_modules/react-dom'].version}`);
  const scheduler = lock.packages['node_modules/react-dom/node_modules/scheduler'] || lock.packages['node_modules/scheduler'];
  assert(dom.dependsOn.includes(`react@${lock.packages['node_modules/react'].version}`) && dom.dependsOn.includes(`scheduler@${scheduler.version}`));
});
