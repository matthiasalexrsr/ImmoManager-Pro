import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { auditNavigation, parseModule, registeredRoutes, navigationTargets, classifyTarget } from './navigationAudit.mjs';

const sample = source => parseModule('/fixture/App.jsx', source);
test('nested/index routes derive prefixes from AST; catch-all cannot validate an unknown link', () => {
  const routes = registeredRoutes(sample('const App = () => <Route path="/workspace"><Route index/><Route path="records/:id"/><Route path="*"/></Route>'));
  assert.deepEqual(routes.map(route => route.path), ['/workspace', '/workspace', '/workspace/records/:id', '/workspace/*']);
  assert.equal(classifyTarget({ pattern: '/workspace/records/a', parameterized: false }, routes).status, 'literal-route-match');
  assert.equal(classifyTarget({ pattern: '/workspace/missing', parameterized: false }, routes).status, 'unregistered-route');
  assert.equal(classifyTarget({ pattern: '/workspace/records', parameterized: false }, routes).status, 'unregistered-route');
});
test('actual JSX, navigation objects, imperative calls and unresolved runtime values remain distinguishable', () => {
  const model = sample('const fixed = "/records"; const Ui = () => <><Link to={fixed}/><AppLink to={`/records/${item.id}?source_id=${child.id}`}/><NavLink to={remote.href}/><Navigate to={{pathname:"/records",search:"?state=open"}}/></>; navigate("/missing"); const menu = {to:"/records?new=1"};');
  const targets = navigationTargets(model);
  assert.equal(targets.length, 6);
  assert.equal(targets[0].variants[0].pattern, '/records');
  assert.equal(targets[1].variants[0].pattern, '/records/__DYNAMIC__?source_id=__DYNAMIC__');
  assert.equal(targets[2].variants[0].unresolved, true);
  assert.equal(targets[3].variants[0].pattern, '/records?state=open');
  const routes = registeredRoutes(sample('const App=()=> <Route path="records"><Route path=":id"/></Route>'));
  assert.equal(classifyTarget(targets[1].variants[0], routes).status, 'parameterized-route-shape');
  assert.equal(classifyTarget(targets[2].variants[0], routes).status, 'runtime-required');
});
test('unsafe and server-document links never silently count as successful SPA routes', () => {
  assert.equal(classifyTarget({pattern:'//elsewhere.example/path'}, []).status, 'unsafe-url');
  assert.equal(classifyTarget({pattern:'/\\elsewhere.example/path'}, []).status, 'unsafe-url');
  assert.equal(classifyTarget({pattern:'/api/v1/legal'}, []).status, 'server-endpoint-requires-separate-verification');
  assert.equal(classifyTarget({pattern:'https://example.com'}, []).status, 'external');
});
test('query inventory follows imported page and inherited layout, including literal-key maps', () => {
  const prefix = resolve(tmpdir()) + sep + 'immo-navigation-';
  const folder = mkdtempSync(prefix);
  try {
    mkdirSync(join(folder, 'frontend/src'), {recursive:true});
    writeFileSync(join(folder, 'frontend/src/App.jsx'), 'import Shell from "./Shell"; import Page from "./Page"; const App=()=> <Route path="/" element={<Shell/>}><Route path="records" element={<Page/>}/><Route path="*"/></Route>');
    writeFileSync(join(folder, 'frontend/src/Shell.jsx'), 'const Shell = () => params.get("new");');
    writeFileSync(join(folder, 'frontend/src/Page.jsx'), 'const KEYS=["parent","state"]; const read=params=>KEYS.map(key=>params.get(key)); const Ui=()=> <><Link to="/records?parent=p&new=1&ignored=x"/><Link to={runtime.href}/><Link to="/nonexistent"/></>;');
    const report = auditNavigation({repo:folder,backend:false});
    const link = report.targets.find(target => target.expression.includes('ignored='));
    assert.deepEqual(link.variants[0].query.map(item=>[item.key,item.status]), [['parent','reader-found-not-behavior-verified'],['new','reader-found-not-behavior-verified'],['ignored','no-static-reader-found']]);
    assert.equal(report.summary.classifications['unregistered-route'], 1);
    assert.equal(report.summary.classifications['runtime-required'], 1);
    assert.equal(link.variants[0].runtimeRequired,true);
    assert.equal(report.routes.find(route=>route.path==='/records').incomingTargets,1);
  } finally {
    if (!resolve(folder).startsWith(prefix)) throw Error('Refuse cleanup outside owned fixture');
    rmSync(folder, {recursive:true,force:true});
  }
});
test('real source inventory parses every module and all emitted SPA route shapes match the actual router', () => {
  const repo = fileURLToPath(new URL('../..', import.meta.url));
  const report = auditNavigation({repo});
  assert.deepEqual(report.parseErrors, []);
  assert.equal(report.backendStatus.status, 'parsed-with-python-ast');
  assert.ok(report.summary.registeredRoutes > 0);
  const broken = report.targets.flatMap(target => target.variants.filter(variant => ['unregistered-route','unsafe-url'].includes(variant.status)).map(variant=>`${target.file}:${target.line} ${variant.pattern}`));
  assert.deepEqual(broken, []);
  for (const kind of ['workspace-context','global-search']) {
    assert.ok(report.targets.some(target=>target.kind===kind));
    assert.ok(report.targets.filter(target=>target.kind===kind).every(target=>target.variants.every(variant=>variant.status==='parameterized-route-shape')));
  }
  assert.ok(report.targets.some(target=>target.variants.some(variant=>variant.status==='runtime-required')));
});
