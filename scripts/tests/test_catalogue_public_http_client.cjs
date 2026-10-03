const { test } = require('node:test');
const assert = require('node:assert/strict');
const { catalogue } = require('../catalogue_public_http_client.cjs');
const options = { sourceUrl: 'https://example.invalid/public.js', observedOn: '2026-10-02' };

test('lexical shadowing and reassigned base are not mistaken for a known endpoint', () => {
  const value = catalogue(`const base='/api/known'; http.get(base);
    function unknown(base) { http.post(base, {id: 1}); }
    let changing='/api/old'; changing=window.runtimePath; http.get(changing);`, options);
  assert.deepEqual(value.calls.map(item => item.path), ['/api/known']);
});

test('class bases, unknown path variables, spreads and literal values retain their evidence', () => {
  const value = catalogue(`class Client { base='/api/objects'; read(id) {
    return http.post(\`\${this.base}/\${id}\`, {Ref:id,...scope(id), flag:true,
      count:7, empty:null, tags:['original'], [id]:'dynamic'}); } }`, options);
  assert.equal(value.calls[0].path, '/api/objects/{parameter}');
  assert.equal(value.calls[0].inline_key_analysis_complete, false);
  const fields = value.calls[0].arguments[0].fields;
  assert.equal(fields.find(field => field.key === 'count').value.static_value, 7);
  assert.equal(fields.find(field => field.key === 'empty').value.static_value, null);
  assert.equal(fields.find(field => field.kind === 'spread').argument.source_expression, 'scope(id)');
  assert.equal(value.calls[0].live_verified, false);
  assert.equal(value.calls[0].runtime_request_schema_verified, false);
});

test('conflicting class base assignments are left unresolved', () => {
  const value = catalogue(`class Client { base='/api/first'; change() { this.base='/api/second'; }
    read() { http.get(this.base); } }`, options);
  assert.equal(value.call_site_count, 0);
});

test('every call is retained after the hundredth and the client is never executed', () => {
  const input = `throw new Error('must not run');\n` + Array.from({length: 257}, (_, i) =>
    `http.get('/api/item/${i}');`).join('\n');
  const value = catalogue(input, options);
  assert.equal(value.call_site_count, 257);
  assert.ok(value.calls.some(item => item.path === '/api/item/256'));
  assert.equal(value.discovery_does_not_execute_requests, true);
});
