// Static analysis only: never execute/import the downloaded client or make requests.
// Uses the project's existing frontend Babel tooling after `npm ci` in frontend.
const fs = require('node:fs');
const crypto = require('node:crypto');
const { parse } = require('../frontend/node_modules/@babel/parser/lib/index.js');
const traverse = require('../frontend/node_modules/@babel/traverse/lib/index.js').default;

function catalogue(source, { sourceUrl, observedOn }) {
  const ast = parse(source, { sourceType: 'unambiguous' });
  const results = [];
  const basesByClass = new WeakMap();
  function classBases(classPath) {
    if (!classPath) return new Map();
    if (basesByClass.has(classPath.node)) return basesByClass.get(classPath.node);
    const candidates = new Map();
    const add = (key, value) => {
      if (typeof key !== 'string') return;
      if (!candidates.has(key)) candidates.set(key, new Set());
      candidates.get(key).add(value);
    };
    classPath.traverse({
      Class(path) { path.skip(); },
      ClassProperty(path) {
        if (path.node.static) return;
        const key = path.node.computed ? null : path.node.key.name ?? path.node.key.value;
        add(key, path.node.value?.type === 'StringLiteral' ? path.node.value.value : null);
      },
      AssignmentExpression(path) {
        const left = path.node.left;
        if (left.type !== 'MemberExpression' || left.object.type !== 'ThisExpression') return;
        const key = left.computed ? (left.property.type === 'StringLiteral' ? left.property.value : null) : left.property.name;
        add(key, path.node.right.type === 'StringLiteral' ? path.node.right.value : null);
      },
    });
    const bases = new Map([...candidates].filter(([, values]) => values.size === 1 && !values.has(null))
      .map(([key, values]) => [key, [...values][0]]));
    basesByClass.set(classPath.node, bases);
    return bases;
  }
  function staticValue(path, bases) {
    if (!path?.node) return null;
    const node = path.node;
    if (node.type === 'StringLiteral') return node.value;
    if (node.type === 'Identifier') {
      // Resolve the actual lexical binding; a parameter named like a global
      // constant must never inherit that constant's unrelated URL.
      const binding = path.scope.getBinding(node.name);
      return binding?.constant && binding.path.isVariableDeclarator()
        && binding.path.node.init?.type === 'StringLiteral' ? binding.path.node.init.value : null;
    }
    if (node.type === 'MemberExpression' && node.object.type === 'ThisExpression') {
      const key = node.computed ? (node.property.type === 'StringLiteral' ? node.property.value : null) : node.property.name;
      return bases.get(key) ?? null;
    }
    if (node.type === 'TemplateLiteral') {
      const expressions = path.get('expressions');
      return node.quasis.map((q, i) => q.value.cooked + (i < expressions.length
        ? staticValue(expressions[i], bases) ?? '{parameter}' : '')).join('');
    }
    if (node.type === 'BinaryExpression' && node.operator === '+') {
      const left = staticValue(path.get('left'), bases);
      const right = staticValue(path.get('right'), bases);
      return left !== null && right !== null ? left + right : null;
    }
    return null;
  }
  function argumentEvidence(node) {
    if (!node) return { present: false };
    const evidence = { present: true, syntax: node.type, source_expression: source.slice(node.start, node.end) };
    if (['StringLiteral', 'NumericLiteral', 'BooleanLiteral', 'NullLiteral'].includes(node.type)) {
      evidence.static_value = node.type === 'NullLiteral' ? null : node.value;
    }
    if (node.type === 'ObjectExpression') {
      evidence.fields = node.properties.map(property => {
        if (property.type === 'SpreadElement') return { kind: 'spread', argument: argumentEvidence(property.argument) };
        return { kind: property.type, computed: Boolean(property.computed),
          key: !property.computed ? property.key.name ?? property.key.value : null,
          key_expression: source.slice(property.key.start, property.key.end),
          ...(property.value ? { value: argumentEvidence(property.value) } : {}) };
      });
      evidence.inline_key_analysis_complete = node.properties.every(p => p.type === 'ObjectProperty' && !p.computed);
    }
    if (node.type === 'ArrayExpression') evidence.elements = node.elements.map(argumentEvidence);
    if (node.type === 'ConditionalExpression') {
      evidence.condition = argumentEvidence(node.test);
      evidence.if_true = argumentEvidence(node.consequent);
      evidence.if_false = argumentEvidence(node.alternate);
    }
    return evidence;
  }
  traverse(ast, {
    CallExpression(path) {
      const node = path.node;
      if (node.callee.type !== 'MemberExpression') return;
      const method = node.callee.computed ? node.callee.property.value : node.callee.property.name;
      if (!['get', 'post', 'put', 'patch', 'delete', 'head'].includes(method)) return;
      const bases = classBases(path.findParent(p => p.isClass()));
      const route = staticValue(path.get('arguments.0'), bases);
      if (!route?.startsWith('/api/')) return;
      const data = node.arguments[1];
      const keys = data?.type === 'ObjectExpression' ? data.properties
        .filter(p => p.type === 'ObjectProperty' && !p.computed).map(p => p.key.name ?? p.key.value) : [];
      results.push({ method: method.toUpperCase(), path: route,
        inline_second_argument_keys: keys,
        inline_key_analysis_complete: Boolean(data?.type === 'ObjectExpression'
          && data.properties.every(p => p.type === 'ObjectProperty' && !p.computed)),
        arguments: node.arguments.slice(1).map(argumentEvidence),
        url_expression: source.slice(node.arguments[0].start, node.arguments[0].end),
        source_offset: node.start, evidence: 'static-public-client-call',
        live_verified: false, runtime_request_schema_verified: false });
    },
  });
  results.sort((a, b) => a.path.localeCompare(b.path) || a.method.localeCompare(b.method) || a.source_offset - b.source_offset);
  return { catalogue_version: 1, observed_on: observedOn, source_url: sourceUrl,
    source_sha256: crypto.createHash('sha256').update(source).digest('hex'), source_bytes: Buffer.byteLength(source),
    evidence_scope: 'Static public client call sites, not an exhaustive server specification or live probe.',
    values_scope: 'Public literal values and symbolic request expressions only; no authenticated account values.',
    keys_scope: 'Direct inline keys are incomplete when computed, spread or identifier-defined; arguments retain exact public expressions.',
    discovery_does_not_execute_requests: true, call_site_count: results.length, calls: results };
}

if (require.main === module) {
  const [input, output, sourceUrl, observedOn] = process.argv.slice(2);
  if (!input || !output || !sourceUrl || !/^\d{4}-\d{2}-\d{2}$/.test(observedOn ?? '')) {
    process.stderr.write('Usage: node scripts/catalogue_public_http_client.cjs public-client.js catalogue.json source-url YYYY-MM-DD\n');
    process.exitCode = 2;
  } else {
    const result = catalogue(fs.readFileSync(input, 'utf8'), { sourceUrl, observedOn });
    fs.writeFileSync(output, JSON.stringify(result, null, 2) + '\n');
    process.stdout.write(JSON.stringify({ call_sites: result.call_site_count, source_sha256: result.source_sha256 }) + '\n');
  }
}

module.exports = { catalogue };
