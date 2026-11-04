import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { evaluateAudit } from './auditDependencies.mjs';

const frontend = fileURLToPath(new URL('..', import.meta.url));
const policy = JSON.parse(readFileSync(join(frontend, 'scripts/auditExceptions.json'), 'utf8'));
const rule = policy.entries[0];
const reviewedCode = readFileSync(join(frontend, 'node_modules/minimatch/minimatch.js'));
const now = new Date('2026-11-04T00:00:00Z');

function fixture(run) {
  const prefix = resolve(tmpdir()) + sep + 'immo-audit-';
  const root = mkdtempSync(prefix);
  try {
    mkdirSync(join(root, 'node_modules/minimatch'), { recursive: true });
    writeFileSync(join(root, 'node_modules/minimatch/minimatch.js'), reviewedCode);
    writeFileSync(join(root, 'node_modules/minimatch/package.json'), JSON.stringify({ name: 'minimatch', version: rule.version, main: rule.entrypoint }));
    writeFileSync(join(root, 'package-lock.json'), JSON.stringify({ packages: { 'node_modules/minimatch': { version: rule.version, dev: true } } }));
    const advisory = { name: rule.package, dependency: rule.package, url: rule.url, source: rule.source,
      range: rule.range, severity: rule.severity, title: rule.title };
    const report = { auditReportVersion: 2, vulnerabilities: {
      eslint: { name: 'eslint', via: ['eslint-utils', 'minimatch'], nodes: ['node_modules/eslint'] },
      'eslint-utils': { name: 'eslint-utils', via: ['eslint'], nodes: ['node_modules/eslint-utils'] },
      minimatch: { name: 'minimatch', via: [advisory], nodes: ['node_modules/minimatch'] },
    }, metadata: { vulnerabilities: { total: 3 } } };
    const check = (input = report, extra = {}) => evaluateAudit(input, { root, exceptions: policy, now, ...extra });
    run({ root, report, advisory, check });
  } finally {
    if (!resolve(root).startsWith(prefix)) throw Error('Refuse cleanup outside owned audit fixture');
    rmSync(root, { recursive: true, force: true });
  }
}

test('accepts only the reviewed legacy code and grounded indirect cycles', () => fixture(({ check }) => {
  const decision = check();
  assert.equal(decision.passed, true);
  assert.deepEqual(decision.accepted, ['eslint', 'eslint-utils', 'minimatch']);
  assert.deepEqual(decision.advisory_ids, [rule.url]);
  assert.equal(decision.reviewed_exceptions[0].sha256, rule.sha256);
  assert.equal(decision.reviewed_exceptions[0].review_until, rule.review_until);
  assert.deepEqual(decision.remaining, []);
}));
test('an unrelated advisory stays blocking even through an indirect chain', () => fixture(({ report, check }) => {
  report.vulnerabilities.minimatch.via.push({ url: 'https://github.com/advisories/GHSA-new-real-issue', name: 'minimatch' });
  assert.equal(check().passed, false);
}));
test('an actually affected version is refused', () => fixture(({ root, check }) => {
  writeFileSync(join(root, 'node_modules/minimatch/package.json'), JSON.stringify({ name: 'minimatch', version: '10.2.6', main: rule.entrypoint }));
  assert.throws(() => check(), /installed development dependency/);
}));
test('changed source is refused even at the same version', () => fixture(({ root, check }) => {
  writeFileSync(join(root, 'node_modules/minimatch/minimatch.js'), Buffer.concat([reviewedCode, Buffer.from('\n// changed\n')]));
  assert.throws(() => check(), /code changed/);
}));
test('a runtime dependency cannot use the development exception', () => fixture(({ root, check }) => {
  writeFileSync(join(root, 'package-lock.json'), JSON.stringify({ packages: { 'node_modules/minimatch': { version: rule.version, dev: false } } }));
  assert.throws(() => check(), /installed development dependency/);
}));
test('an expired review is blocking', () => fixture(({ check }) => {
  assert.equal(check(undefined, { now: new Date('2026-12-05T00:00:00Z') }).passed, false);
}));
test('changed advisory facts are blocking', () => fixture(({ advisory, check }) => {
  advisory.range = '<=3.1.5';
  assert.equal(check().passed, false);
}));
test('a cycle without an advisory leaf is refused', () => fixture(({ report, check }) => {
  report.vulnerabilities.eslint.via = ['eslint-utils'];
  assert.throws(() => check(), /cycle has no reviewed root cause/);
}));
test('missing graph nodes are refused', () => fixture(({ report, check }) => {
  report.vulnerabilities.eslint.via.push('missing-advisory');
  assert.throws(() => check(), /Missing advisory dependency/);
}));
test('network/error responses do not pass the audit', () => fixture(({ check }) => {
  assert.throws(() => check({ error: { code: 'ENOAUDIT' } }), /complete audit report/);
}));
test('invalid or inconsistent audit metadata is refused', () => fixture(({ report, check }) => {
  report.metadata.vulnerabilities.total = 0;
  assert.throws(() => check(), /Inconsistent vulnerability count/);
}));
test('a clean registry result needs neither an exception nor installed legacy code', () => {
  const clean = { auditReportVersion: 2, vulnerabilities: {}, metadata: { vulnerabilities: { total: 0 } } };
  assert.deepEqual(evaluateAudit(clean, { root: '/not-needed' }), { passed: true, accepted: [], advisory_ids: [], reviewed_exceptions: [], remaining: [] });
});
