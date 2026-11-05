import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import process from 'node:process';
import { fileURLToPath, URL } from 'node:url';

export const scope = 'Locked frontend build dependency inventory, including development and all-platform optional packages; not an inventory of files shipped in the binary.';
const frontend = fileURLToPath(new URL('..', import.meta.url));
const hash = value => createHash('sha256').update(value).digest('hex');
const identity = (location, item) => `${item.name || location.split('node_modules/').at(-1)}@${item.version}`;
const sorted = values => [...values].sort();

export function validateInventory(bom, manifest, lock) {
  assert(bom?.bomFormat === 'CycloneDX' && Array.isArray(bom.components) && Array.isArray(bom.dependencies), 'Malformed CycloneDX inventory');
  assert(lock?.lockfileVersion === 3 && lock.packages?.[''], 'A version-3 package lock is required');
  for (const field of ['dependencies', 'devDependencies', 'optionalDependencies']) {
    assert.deepEqual(lock.packages[''][field] || {}, manifest[field] || {}, `package.json/lock ${field} differ`);
  }
  const root = `${manifest.name}@${manifest.version}`;
  assert.equal(bom.metadata?.component?.['bom-ref'], root, 'Unexpected root component');
  assert.equal(bom.metadata.component.name, manifest.name, 'Unexpected root name');
  assert.equal(bom.metadata.component.version, manifest.version, 'Unexpected root version');
  const packages = Object.entries(lock.packages).filter(([location]) => location);
  assert(packages.every(([, item]) => !item.link && typeof item.version === 'string'), 'Unsupported linked or unversioned lock component');
  const expected = new Set(packages.map(([location, item]) => identity(location, item)));
  const components = new Map();
  for (const item of bom.components) {
    const ref = item?.['bom-ref'];
    assert(typeof ref === 'string' && !components.has(ref) && ref !== root, 'Duplicate or malformed component');
    assert.equal(ref, `${item.name}@${item.version}`, 'Component identity/version mismatch');
    assert(expected.has(ref), `Unexpected component/version: ${ref}`);
    components.set(ref, item);
  }
  assert.deepEqual(sorted(components.keys()), sorted(expected), 'Missing locked components');
  const refs = new Set([root, ...components.keys()]), graph = new Map();
  for (const edge of bom.dependencies) {
    assert(refs.has(edge?.ref) && !graph.has(edge.ref) && Array.isArray(edge.dependsOn), 'Duplicate or malformed graph entry');
    assert(new Set(edge.dependsOn).size === edge.dependsOn.length && edge.dependsOn.every(ref => refs.has(ref)), 'Dangling or duplicate dependency reference');
    graph.set(edge.ref, new Set(edge.dependsOn));
  }
  assert.deepEqual(sorted(graph.keys()), sorted(refs), 'Missing graph entries');
  const target = (location, name) => {
    for (;;) {
      const candidate = `${location ? location + '/' : ''}node_modules/${name}`;
      if (lock.packages[candidate]) return candidate;
      if (!location) return null;
      const parent = location.lastIndexOf('/node_modules/');
      location = parent < 0 ? '' : location.slice(0, parent);
    }
  };
  const lockedGraph = new Map([...refs].map(ref => [ref, new Set()]));
  let lockEdges = 0;
  for (const [location, item] of Object.entries(lock.packages)) {
    const from = location ? identity(location, item) : root;
    const dependencies = { ...item.dependencies, ...item.optionalDependencies, ...item.peerDependencies, ...(!location && item.devDependencies) };
    for (const name of Object.keys(dependencies)) {
      const found = target(location, name);
      const optional = Object.hasOwn(item.optionalDependencies || {}, name) || item.peerDependenciesMeta?.[name]?.optional === true;
      assert(found || optional, `Unresolved required lock dependency: ${location}/${name}`);
      if (found) { lockedGraph.get(from).add(identity(found, lock.packages[found])); lockEdges++; }
    }
  }
  for (const [ref, edges] of lockedGraph) assert.deepEqual(sorted(graph.get(ref)), sorted(edges), `Locked graph edges differ: ${ref}`);
  const production = Object.keys(manifest.dependencies || {}).map(name => {
    const location = target('', name);
    assert(location, `Missing production dependency: ${name}`);
    return identity(location, lock.packages[location]);
  });
  const closure = new Set(), pending = [...production];
  while (pending.length) { const ref = pending.pop(); if (!closure.has(ref)) { closure.add(ref); pending.push(...graph.get(ref)); } }
  return { scope, lock_locations: packages.length, components: components.size, root_dependencies: graph.get(root).size,
    production_direct_dependencies: production, production_closure_components: sorted(closure), validated_lock_edges: lockEdges,
    production_closure_scope: 'Locked dependencies and available optional/peer edges reachable from production roots; not a binary payload inventory.' };
}

export function generateInventory(root = frontend) {
  const manifestBytes = readFileSync(join(root, 'package.json')), lockBytes = readFileSync(join(root, 'package-lock.json'));
  // Primary CLI contract: https://docs.npmjs.com/cli/v11/commands/npm-sbom/#package-lock-only-mode
  // Measured npm 11.19 omit-dev modes lose React/ReactDOM. Include every type and validate the entire lock graph.
  const args = ['sbom', '--package-lock-only', '--include=dev', '--include=prod', '--include=optional', '--include=peer', '--sbom-format=cyclonedx', '--offline', '--ignore-scripts'];
  let command = 'npm';
  if (process.platform === 'win32') {
    const found = spawnSync('where.exe', ['npm.cmd'], { encoding: 'utf8', timeout: 10000 });
    const cli = found.stdout?.trim().split(/\r?\n/).map(path => join(dirname(path), 'node_modules/npm/bin/npm-cli.js')).find(existsSync);
    assert(!found.error && found.status === 0 && cli, 'Cannot locate the installed npm CLI');
    command = process.execPath; args.unshift(cli);
  }
  const result = spawnSync(command, args, { cwd: root, encoding: 'utf8', timeout: 60000, maxBuffer: 32 * 1024 * 1024 });
  assert(!result.error && result.status === 0, `npm SBOM failed: ${result.error?.message || result.stderr || result.status}`);
  const bom = JSON.parse(result.stdout), report = validateInventory(bom, JSON.parse(manifestBytes), JSON.parse(lockBytes));
  assert.equal(hash(readFileSync(join(root, 'package.json'))), hash(manifestBytes), 'Manifest changed during generation');
  assert.equal(hash(readFileSync(join(root, 'package-lock.json'))), hash(lockBytes), 'Lock changed during generation');
  bom.metadata.component.description = scope;
  bom.metadata.properties = [...(bom.metadata.properties || []), { name: 'immomanager:inventory:scope', value: scope },
    { name: 'immomanager:inventory:package-lock-sha256', value: hash(lockBytes) }];
  return { bom, report: { ...report, package_json_sha256: hash(manifestBytes), package_lock_sha256: hash(lockBytes),
    node: process.version, npm: bom.metadata.tools?.find(tool => tool.vendor === 'npm')?.version } };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  assert(process.argv.length === 3, 'Usage: node scripts/frontendSbom.mjs OUTPUT.cdx.json');
  const output = resolve(process.argv[2]), { bom, report } = generateInventory();
  const content = JSON.stringify(bom, null, 2) + '\n';
  writeFileSync(output, content);
  writeFileSync(output + '.validation.json', JSON.stringify({ ...report, sbom_sha256: hash(content) }, null, 2) + '\n');
  process.stdout.write(JSON.stringify({ components: report.components, production_direct: report.production_direct_dependencies.length,
    production_closure: report.production_closure_components.length, validated_lock_edges: report.validated_lock_edges }) + '\n');
}
