// Diagnostic for the known revision-metadata gap; reads actual E2E artifacts only.
// Not part of the passing transport/isolation suite. It intentionally fails on 6b58ab3.
// Usage: node e2e/assert-revision-counter.mjs <path-to-revision-records.json>
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

if (process.argv.length !== 3) {
  throw new Error('Usage: node e2e/assert-revision-counter.mjs <revision-records.json>');
}
const records = JSON.parse(await readFile(process.argv[2], 'utf8'));
const expected = records.revisionResponse?.revision;
assert.ok(Number.isInteger(expected) && expected > 1, 'Expected a correction revision > 1');
assert.ok(Array.isArray(records.correction) && records.correction.length > 0, 'Missing actual generated statements');
const actual = records.correction.map(row => ({ statement: row.id, revision: row.revision }));
console.log(JSON.stringify({ expected, actual }, null, 2));
assert.ok(actual.every(row => row.revision === expected),
  'Persisted statement/PDF revision does not match the revision API response. See UI_BILLING_E2E_HANDOFF.md.');
