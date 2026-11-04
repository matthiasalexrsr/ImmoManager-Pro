import { createHash } from 'node:crypto';
import { existsSync, readFileSync, realpathSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const defaultRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');

function inspectInstalled(root, node, exception, lock) {
  if (typeof node !== 'string' || !/^node_modules\//.test(node)) throw Error('Unexpected audit dependency path');
  const folder = realpathSync(resolve(root, node));
  const inside = relative(realpathSync(root), folder);
  if (inside.startsWith('..' + sep) || inside === '..' || isAbsolute(inside)) throw Error('Dependency outside the installation');
  const metadata = JSON.parse(readFileSync(join(folder, 'package.json'), 'utf8'));
  const source = readFileSync(join(folder, exception.entrypoint));
  if (metadata.name !== exception.package || metadata.version !== exception.version
      || metadata.main !== exception.entrypoint || lock.packages?.[node]?.version !== exception.version
      || lock.packages[node].dev !== true) throw Error('The audit exception does not match the installed development dependency');
  if (createHash('sha256').update(source).digest('hex') !== exception.sha256) throw Error('The reviewed dependency code changed');
  if (source.includes('firstPhasePreProcess') || source.includes('optimizationLevel')) throw Error('The described preprocessing implementation is present');
}

/** All advisory leaves must be reviewed; cycles alone never justify an exception. */
export function evaluateAudit(report, { root = defaultRoot, now = new Date(), exceptions } = {}) {
  if (report?.error || report?.auditReportVersion !== 2 || !report.vulnerabilities || !report.metadata?.vulnerabilities) throw Error('npm did not return a complete audit report');
  const vulnerabilities = new Map(Object.entries(report.vulnerabilities));
  if (report.metadata.vulnerabilities.total !== vulnerabilities.size) throw Error('Inconsistent vulnerability count');
  if (!vulnerabilities.size) {
    if (report.metadata.vulnerabilities.total !== 0) throw Error('Inconsistent empty audit report');
    return { passed: true, accepted: [], advisory_ids: [], reviewed_exceptions: [], remaining: [] };
  }
  const policy = exceptions || JSON.parse(readFileSync(join(root, 'scripts/auditExceptions.json'), 'utf8'));
  if (policy.format !== 'immomanager-audit-exceptions/1' || !Array.isArray(policy.entries)) throw Error('Unrecognized audit policy');
  const lock = JSON.parse(readFileSync(join(root, 'package-lock.json'), 'utf8'));
  const accepted = new Set();
  const verified = new Set();
  const remaining = [];
  for (const [name, entry] of vulnerabilities) {
    if (entry.name !== name || !Array.isArray(entry.via) || !entry.via.length) throw Error('Incomplete vulnerability graph');
    for (const via of entry.via) {
      if (typeof via === 'string') {
        if (!vulnerabilities.has(via)) throw Error('Missing advisory dependency');
        continue;
      }
      const exception = policy.entries.find(rule => rule.package === name && rule.url === via?.url);
      const expires = exception && Date.parse(exception.review_until + 'T23:59:59Z');
      if (!exception || !Number.isFinite(expires) || !Number.isFinite(now.getTime()) || via.name !== exception.package || via.dependency !== exception.package
          || via.source !== exception.source || via.range !== exception.range || via.severity !== exception.severity
          || via.title !== exception.title || now.getTime() > expires) {
        remaining.push(via?.url || name);
        continue;
      }
      if (!Array.isArray(entry.nodes) || !entry.nodes.length) throw Error('Missing installed package paths');
      if (!verified.has(name)) {
        for (const node of entry.nodes) inspectInstalled(root, node, exception, lock);
        verified.add(name);
      }
      accepted.add(via.url);
    }
  }
  if (remaining.length) return { passed: false, accepted: [], advisory_ids: [], reviewed_exceptions: [], remaining: [...new Set(remaining)] };
  function reachesReviewedLeaf(name, visiting = new Set()) {
    if (visiting.has(name)) return false;
    const path = new Set(visiting).add(name);
    return vulnerabilities.get(name).via.some(via => typeof via === 'string'
      ? reachesReviewedLeaf(via, path) : accepted.has(via.url));
  }
  for (const name of vulnerabilities.keys()) {
    if (!reachesReviewedLeaf(name)) throw Error('An advisory cycle has no reviewed root cause');
  }
  const reviewed = policy.entries.filter(entry => accepted.has(entry.url)).map(entry => ({
    advisory: entry.advisory, package: entry.package, version: entry.version,
    sha256: entry.sha256, review_until: entry.review_until, reason: entry.reason,
  }));
  return { passed: true, accepted: [...vulnerabilities.keys()], advisory_ids: [...accepted], reviewed_exceptions: reviewed, remaining: [] };
}

export function runAudit(root = defaultRoot) {
  let command = 'npm', args = ['audit', '--json', '--audit-level=low'];
  if (process.platform === 'win32') {
    const found = spawnSync('where.exe', ['npm.cmd'], { encoding: 'utf8', timeout: 10000 });
    const cli = found.stdout?.trim().split(/\r?\n/).map(path => join(dirname(path), 'node_modules/npm/bin/npm-cli.js')).find(existsSync);
    if (found.error || found.status !== 0 || !cli) throw Error('Cannot locate the installed npm CLI');
    command = process.execPath; args = [cli, ...args];
  }
  const audit = spawnSync(command, args,
    { cwd: root, encoding: 'utf8', maxBuffer: 16 * 1024 * 1024, timeout: 60000 });
  if (audit.error || ![0, 1].includes(audit.status)) throw audit.error || Error('npm audit did not complete');
  const report = JSON.parse(audit.stdout);
  const output = join(root, 'artifacts/npm-audit');
  mkdirSync(output, { recursive: true });
  writeFileSync(join(output, 'audit.json'), JSON.stringify(report, null, 2));
  const result = evaluateAudit(report, { root });
  if (audit.status === 1 && !Object.keys(report.vulnerabilities).length) throw Error('npm audit failed without a vulnerability result');
  writeFileSync(join(output, 'decision.json'), JSON.stringify({ ...result, npm_exit_code: audit.status }, null, 2));
  console.log(JSON.stringify({ ...result, npm_exit_code: audit.status }, null, 2));
  return result.passed ? 0 : 1;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { process.exitCode = runAudit(); }
  catch (error) { console.error('Dependency audit failed: ' + error.message); process.exitCode = 1; }
}
