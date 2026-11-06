/** Source-only navigation inventory. It never starts the app or contacts a server.
 * A route match proves URL structure only, never authorization, data existence,
 * query effects, acknowledgement, browser history, or a successful detail load.
 */
import { readFileSync, readdirSync, existsSync, writeFileSync, mkdirSync } from 'node:fs';
import { resolve, dirname, join, extname, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';

const ownPath = fileURLToPath(import.meta.url);
const require = createRequire(import.meta.url);
const { parse } = require('espree');
const dynamic = '__DYNAMIC__';
const slashes = value => value.replaceAll('\\', '/');
const compact = value => value.replace(/\s+/g, ' ').slice(0, 220);
function walk(node, callback, parents = []) {
  if (!node || typeof node !== 'object') return;
  if (typeof node.type === 'string') callback(node, parents);
  for (const [key, value] of Object.entries(node)) {
    if (['loc', 'range', 'tokens', 'comments', 'parent'].includes(key)) continue;
    if (Array.isArray(value)) value.forEach(child => walk(child, callback, [...parents, node]));
    else if (value && typeof value === 'object') walk(value, callback, [...parents, node]);
  }
}
const nameOf = node => node?.name || node?.value;
const jsxName = node => node?.type === 'JSXIdentifier' ? node.name : null;
function sourceFiles(folder) {
  return readdirSync(folder, { withFileTypes: true }).flatMap(entry => {
    const name = join(folder, entry.name);
    if (entry.isDirectory()) return ['test', '__tests__', 'node_modules'].includes(entry.name) ? [] : sourceFiles(name);
    return /\.[cm]?[jt]sx?$/.test(name) && !/\.(test|spec)\./.test(name) ? [name] : [];
  });
}
function modulePath(filename, specifier) {
  if (!specifier?.startsWith('.')) return null;
  const stem = resolve(dirname(filename), specifier);
  return [stem, ...['.js', '.jsx', '.mjs', '.ts', '.tsx', '/index.js', '/index.jsx'].map(suffix => stem + suffix)]
    .find(candidate => existsSync(candidate) && extname(candidate)) || null;
}
export function parseModule(filename, source) {
  const ast = parse(source, { ecmaVersion: 'latest', sourceType: 'module', ecmaFeatures: { jsx: true }, loc: true, range: true });
  const model = { filename, source, ast, bindings: new Map(), imports: new Map(), queryReaders: [], dynamicQueryReaders: [] };
  const duplicates = new Set();
  const bind = (key, value) => { if (model.bindings.has(key)) duplicates.add(key); else model.bindings.set(key, value); };
  walk(ast, node => {
    if (node.type === 'VariableDeclarator' && node.id.type === 'Identifier') bind(node.id.name, node.init);
    if (node.type === 'ImportDeclaration') for (const item of node.specifiers) model.imports.set(item.local.name, modulePath(filename, node.source.value));
    if (node.type === 'VariableDeclarator' && node.id.type === 'Identifier' && node.init?.type === 'CallExpression') {
      walk(node.init, child => { if (child.type === 'ImportExpression') model.imports.set(node.id.name, modulePath(filename, child.source.value)); });
    }
  });
  for (const key of duplicates) model.bindings.delete(key); // no unsafe cross-function name resolution
  const arrayKeys = (node, seen = new Set()) => {
    if (node?.type === 'Identifier' && !seen.has(node.name)) return arrayKeys(model.bindings.get(node.name), new Set([...seen, node.name]));
    if (node?.type === 'ArrayExpression') return node.elements.flatMap(item => item?.type === 'SpreadElement' ? arrayKeys(item.argument, seen)
      : item?.type === 'Literal' && typeof item.value === 'string' ? [item.value] : []);
    return [];
  };
  walk(ast, (node, parents) => {
    if (node.type !== 'CallExpression' || node.callee.type !== 'MemberExpression' || !['get', 'getAll', 'has'].includes(nameOf(node.callee.property))) return;
    const receiver = source.slice(...node.callee.object.range);
    if (!/(?:URLSearchParams|searchParams|urlParams|routeQuery|queryParams|\bparams\b|\bquery\b)/i.test(receiver)) return;
    const key = node.arguments[0];
    const reader = { line: node.loc.start.line, expression: compact(source.slice(...node.range)) };
    const strings = key?.type === 'Literal' && typeof key.value === 'string' ? [key.value]
      : key?.type === 'ConditionalExpression' ? [key.consequent, key.alternate].filter(item => item.type === 'Literal' && typeof item.value === 'string').map(item => item.value) : [];
    if (key?.type === 'Identifier') {
      for (const parent of parents) {
        if (parent.type === 'CallExpression' && parent.callee.type === 'MemberExpression'
          && ['map', 'flatMap', 'forEach', 'filter', 'some', 'every'].includes(nameOf(parent.callee.property))
          && parent.arguments.some(arg => arg.type === 'ArrowFunctionExpression' && arg.params[0]?.name === key.name)) strings.push(...arrayKeys(parent.callee.object));
      }
    }
    if (strings.length) for (const name of new Set(strings)) model.queryReaders.push({ ...reader, key: name, inferredFromLiteralKeyCollection: key.type !== 'Literal' });
    else model.dynamicQueryReaders.push(reader);
  });
  return model;
}
function unique(values) { return [...new Map(values.map(value => [JSON.stringify(value), value])).values()]; }
function unknown(node, model, reason = 'runtime expression') {
  return [{ pattern: dynamic, unresolved: true, parameterized: true, reason, expression: node?.range ? compact(model.source.slice(...node.range)) : '' }];
}
function values(node, model, seen = new Set()) {
  if (!node) return unknown(node, model);
  if (node.type === 'JSXExpressionContainer' || node.type === 'ChainExpression') return values(node.expression, model, seen);
  if (node.type === 'Literal' && typeof node.value === 'string') return [{ pattern: node.value, unresolved: false, parameterized: false }];
  if (node.type === 'Identifier' && !seen.has(node.name) && model.bindings.has(node.name)) return values(model.bindings.get(node.name), model, new Set([...seen, node.name]));
  if (node.type === 'ConditionalExpression' || node.type === 'LogicalExpression') return unique([
    ...values(node.type === 'ConditionalExpression' ? node.consequent : node.left, model, seen),
    ...values(node.type === 'ConditionalExpression' ? node.alternate : node.right, model, seen),
  ]);
  if (node.type === 'TemplateLiteral') {
    let result = [{ pattern: node.quasis[0].value.cooked, unresolved: false, parameterized: false }];
    for (let index = 0; index < node.expressions.length; index++) {
      const expression = node.expressions[index];
      const parts = values(expression, model, seen);
      result = result.flatMap(base => parts.map(part => ({ pattern: base.pattern + part.pattern + node.quasis[index + 1].value.cooked,
        // An unknown complete segment is a route parameter, not an unknown base route.
        unresolved: base.unresolved || part.unresolved, parameterized: base.parameterized || part.parameterized })));
    }
    return unique(result).slice(0, 100);
  }
  if (node.type === 'BinaryExpression' && node.operator === '+') return values(node.left, model, seen).flatMap(a => values(node.right, model, seen).map(b => ({
    pattern: a.pattern + b.pattern, unresolved: a.unresolved || b.unresolved, parameterized: a.parameterized || b.parameterized,
  }))).slice(0, 100);
  if (node.type === 'ObjectExpression') {
    const pathname = node.properties.find(item => nameOf(item.key) === 'pathname');
    const search = node.properties.find(item => nameOf(item.key) === 'search');
    if (pathname) return values(pathname.value, model, seen).flatMap(a => search ? values(search.value, model, seen).map(b => ({
      pattern: a.pattern + b.pattern, unresolved: a.unresolved || b.unresolved, parameterized: a.parameterized || b.parameterized,
    })) : [a]);
  }
  if (node.type === 'MemberExpression' && node.object.type === 'Identifier') {
    const object = model.bindings.get(node.object.name);
    if (object?.type === 'ObjectExpression') {
      const key = node.computed ? node.property.value : node.property.name;
      const property = object.properties.find(item => nameOf(item.key) === key);
      if (property) return values(property.value, model, seen);
    }
  }
  return unknown(node, model);
}
export function registeredRoutes(model) {
  const routes = [];
  const functions = new Map(model.ast.body.filter(node => node.type === 'FunctionDeclaration').map(node => [node.id.name, node]));
  const componentFiles = (component, visited = new Set()) => {
    if (visited.has(component)) return [];
    if (model.imports.get(component)) return [model.imports.get(component)];
    const local = functions.get(component), files = [];
    if (local) walk(local, node => { if (node.type === 'JSXOpeningElement') files.push(...componentFiles(jsxName(node.name), new Set([...visited, component]))); });
    return files;
  };
  function visit(node, parentPath = '/', inheritedFiles = []) {
    if (!node || typeof node !== 'object') return;
    let childPath = parentPath;
    let childFiles = inheritedFiles;
    if (node.type === 'JSXElement' && jsxName(node.openingElement.name) === 'Route') {
      const attrs = node.openingElement.attributes;
      const path = attrs.find(item => item.name?.name === 'path');
      const index = attrs.some(item => item.name?.name === 'index');
      if (path) {
        const text = values(path.value, model)[0];
        childPath = text.unresolved ? dynamic : text.pattern.startsWith('/') ? text.pattern : `${parentPath.replace(/\/$/, '')}/${text.pattern}`;
      }
      const element = attrs.find(item => item.name?.name === 'element');
      const components = [];
      if (element) walk(element, child => { if (child.type === 'JSXOpeningElement') components.push(jsxName(child.name)); });
      childFiles = [...new Set([...inheritedFiles, ...components.flatMap(component => componentFiles(component))])];
      if (path || index) routes.push({ path: childPath, index, catchAll: childPath.includes('*'), line: node.loc.start.line,
        components, componentFiles: childFiles });
    }
    for (const [key, value] of Object.entries(node)) {
      if (['loc', 'range'].includes(key)) continue;
      if (Array.isArray(value)) value.forEach(child => visit(child, childPath, childFiles));
      else if (value && typeof value === 'object') visit(value, childPath, childFiles);
    }
  }
  visit(model.ast);
  return routes;
}
export function navigationTargets(model) {
  const targets = [];
  const add = (node, target, kind) => targets.push({ line: node.loc.start.line, kind,
    expression: compact(model.source.slice(...target.range)), variants: values(target, model) });
  walk(model.ast, (node, parents) => {
    if (node.type === 'JSXOpeningElement') {
      const tag = jsxName(node.name);
      const attribute = node.attributes.find(item => ['Link', 'AppLink', 'NavLink', 'Navigate'].includes(tag) ? item.name?.name === 'to' : tag === 'a' && item.name?.name === 'href');
      if (attribute?.value) add(node, attribute.value, `jsx:${tag}`);
    }
    if (node.type === 'CallExpression') {
      const callee = node.callee;
      const isNavigate = callee.type === 'Identifier' && /^(?:navigate|nav|goTo)$/.test(callee.name);
      const isLocation = callee.type === 'MemberExpression' && ['assign', 'replace'].includes(nameOf(callee.property)) && /(?:window\.)?location$/.test(model.source.slice(...callee.object.range));
      if ((isNavigate || isLocation) && node.arguments[0]) add(node, node.arguments[0], isNavigate ? 'navigate' : 'location');
    }
    // Navigation configuration is often rendered by a shared component elsewhere.
    if (node.type === 'Property' && ['to', 'href', 'link', 'metricTo', 'actionTo'].includes(nameOf(node.key))) add(node, node.value, 'navigation-data');
    // These two central factories are actually invoked by EntityLink/assistant links.
    if (/[/\\](entityLinks|assistantLinks)\.js$/.test(model.filename)
      && node.type === 'TemplateLiteral' && parents.some(parent => ['ArrowFunctionExpression', 'ReturnStatement'].includes(parent.type))) add(node, node, 'navigation-factory');
  });
  return targets;
}
function routeMatches(route, pathname) {
  if (route.catchAll || route.path.includes(dynamic)) return false;
  const expected = route.path.split('/').filter(Boolean), actual = pathname.replace(/\/$/, '').split('/').filter(Boolean);
  return expected.length === actual.length && expected.every((segment, index) => segment.startsWith(':') ? Boolean(actual[index]) : segment === actual[index]);
}
export function classifyTarget(variant, routes) {
  const target = variant.pattern;
  if (/^(?:https?:|mailto:|tel:|data:|blob:)/i.test(target)) return { status: 'external', matchedRoutes: [] };
  if (target.startsWith('//') || target.includes('\\') || /[\u0000-\u001f\u007f]/.test(target)) return { status: 'unsafe-url', matchedRoutes: [] };
  if (target.startsWith('/api/')) return { status: 'server-endpoint-requires-separate-verification', matchedRoutes: [] };
  if (!target.startsWith('/')) return { status: target.startsWith('#') ? 'same-page-fragment' : 'runtime-required', matchedRoutes: [] };
  const pathname = target.split(/[?#]/, 1)[0];
  if (pathname.split('/').some(segment => segment.includes(dynamic) && segment !== dynamic)) return { status: 'runtime-required', matchedRoutes: [] };
  const matches = routes.filter(route => routeMatches(route, pathname));
  if (matches.length) return { status: variant.parameterized || variant.unresolved ? 'parameterized-route-shape' : 'literal-route-match', matchedRoutes: matches.map(route => route.path) };
  if (pathname.includes(dynamic)) return { status: 'runtime-required', matchedRoutes: [] };
  return { status: 'unregistered-route', matchedRoutes: [] };
}
function dependencies(filename, modules, found = new Set()) {
  if (found.has(filename) || !modules.has(filename)) return found;
  found.add(filename);
  for (const imported of modules.get(filename).imports.values()) if (imported) dependencies(imported, modules, found);
  return found;
}
function queryKeys(pattern) {
  const question = pattern.indexOf('?');
  return question < 0 ? [] : unique(pattern.slice(question + 1).split('#')[0].split('&').map(pair => pair.split('=')[0]).filter(key => key && !key.includes(dynamic)));
}
export function auditNavigation({ repo = resolve(dirname(ownPath), '../..'), backend = true, python = process.env.PYTHON || 'python' } = {}) {
  const frontend = join(repo, 'frontend/src');
  const modules = new Map(), parseErrors = [];
  for (const filename of sourceFiles(frontend)) {
    try { modules.set(filename, parseModule(filename, readFileSync(filename, 'utf8'))); }
    catch (error) { parseErrors.push({ file: slashes(relative(repo, filename)), error: error.message }); }
  }
  const app = modules.get(join(frontend, 'App.jsx'));
  if (!app) throw new Error('Cannot audit without a parsed App.jsx');
  const rawRoutes = registeredRoutes(app);
  const routeQueries = new Map(rawRoutes.map(route => [route.path, [...new Set(route.componentFiles.flatMap(filename => [...dependencies(filename, modules)]))]
    .flatMap(filename => modules.get(filename).queryReaders.map(reader => ({ ...reader, file: slashes(relative(repo, filename)) })))]));
  const targets = [...modules.values()].flatMap(model => navigationTargets(model).map(target => ({ ...target, file: slashes(relative(repo, model.filename)), source: 'frontend' })));
  let backendStatus = { status: backend ? 'not-run' : 'disabled' };
  if (backend) {
    const result = spawnSync(python, [join(repo, 'tools/navigation_sources.py'), '--repo', repo], { encoding: 'utf8', windowsHide: true });
    if (result.status === 0) { const parsed = JSON.parse(result.stdout); targets.push(...parsed.targets); backendStatus = { status: 'parsed-with-python-ast', files: parsed.files, limitations: parsed.limitations }; }
    else backendStatus = { status: 'failed', error: result.error?.message || result.stderr };
  }
  const classified = targets.map(target => ({ ...target, variants: target.variants.map(variant => {
    const classification = classifyTarget(variant, rawRoutes);
    const accepted = classification.matchedRoutes.flatMap(route => routeQueries.get(route) || []);
    const keys = queryKeys(variant.pattern);
    const query = keys.map(key => ({ key, status: accepted.some(reader => reader.key === key) ? 'reader-found-not-behavior-verified' : 'no-static-reader-found',
      readers: accepted.filter(reader => reader.key === key) }));
    return { ...variant, ...classification, query, runtimeRequired: classification.status !== 'literal-route-match' || query.length > 0 };
  }) }));
  const counts = {};
  for (const target of classified) for (const variant of target.variants) counts[variant.status] = (counts[variant.status] || 0) + 1;
  const routes = rawRoutes.map(route => ({ ...route, componentFiles: route.componentFiles.map(filename => slashes(relative(repo, filename))),
    queryReaders: unique(routeQueries.get(route.path) || []),
    dynamicQueryReaders: [...new Set(route.componentFiles.flatMap(filename => [...dependencies(filename, modules)]))]
      .flatMap(filename => modules.get(filename).dynamicQueryReaders.map(reader => ({ ...reader, file: slashes(relative(repo, filename)) }))),
    incomingTargets: classified.filter(target => target.variants.some(variant => variant.matchedRoutes.includes(route.path))).length }));
  return { schemaVersion: 1, generatedAt: new Date().toISOString(), scope: 'source-only-navigation',
    limitations: ['Route matches prove URL structure only; no route/data/ACL/history/layout behavior is inferred.',
      'Dynamic targets remain runtime-required; parameterized route shapes still require actual record/authorization tests.',
      'Query readers are syntactic evidence from transitive local imports, not proof that the parameter selects the intended record.',
      'Unique const bindings only; duplicate names across scopes remain unresolved to avoid unsafe assumptions.',
      'Navigation-data candidates can include values overridden before rendering; confirm candidates before labeling product defects.',
      'Imperative aliases other than navigate/nav/goTo and opaque runtime callbacks require runtime review.'],
    summary: { parsedModules: modules.size, parseErrors: parseErrors.length, registeredRoutes: routes.filter(route => !route.catchAll).length,
      catchAllRoutes: routes.filter(route => route.catchAll).length, targetExpressions: classified.length, variants: Object.values(counts).reduce((a, b) => a + b, 0), classifications: counts },
    parseErrors, backendStatus, routes, targets: classified,
    sourceHashes: [...modules.values()].map(model => ({ file: slashes(relative(repo, model.filename)), sha256: createHash('sha256').update(model.source).digest('hex') })),
  };
}
if (process.argv[1] && resolve(process.argv[1]) === ownPath) {
  const repoIndex = process.argv.indexOf('--repo'), outputIndex = process.argv.indexOf('--output');
  const report = auditNavigation({ repo: repoIndex < 0 ? undefined : resolve(process.argv[repoIndex + 1]), backend: !process.argv.includes('--no-backend') });
  if (outputIndex >= 0) { const output = resolve(process.argv[outputIndex + 1]); mkdirSync(dirname(output), { recursive: true }); writeFileSync(output, JSON.stringify(report, null, 2) + '\n'); }
  process.stdout.write(JSON.stringify({ summary: report.summary, backendStatus: report.backendStatus, parseErrors: report.parseErrors }, null, 2) + '\n');
  if (report.parseErrors.length || report.backendStatus.status === 'failed') process.exitCode = 1;
}
