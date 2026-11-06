import assert from 'node:assert/strict';
import test from 'node:test';
import { currentTotpStep, freshTotpStep } from './totp_qa_steps.mjs';

function clock(wall) {
  let elapsed = 0;
  const waits = [];
  return { waits, options: { now: () => wall, monotonic: () => elapsed,
    sleep: async milliseconds => { waits.push(milliseconds); wall += milliseconds; elapsed += milliseconds; } } };
}

test('the first unused step can be used without waiting or advancing the clock', async () => {
  const fake = clock(31_000);
  assert.equal(await freshTotpStep(-1, fake.options), 1);
  assert.deepEqual(fake.waits, []);
});

test('a consumed step waits for the actual next step and boundary settling', async () => {
  const fake = clock(29_500);
  assert.equal(await freshTotpStep(0, fake.options), 1);
  assert.deepEqual(fake.waits, [650]);
  assert.equal(await freshTotpStep(1, fake.options), 2);
  assert.deepEqual(fake.waits, [650, 30_000]);
});

test('a backwards or stuck wall clock fails by the monotonic deadline', async () => {
  let elapsed = 0;
  let waits = 0;
  await assert.rejects(freshTotpStep(1, { now: () => 10_000, monotonic: () => elapsed,
    sleep: async milliseconds => { elapsed += milliseconds; waits++; } }), /bounded wait/);
  assert.equal(elapsed, 31_000);
  assert.equal(waits, 1);
});

test('a wait that resumes after its deadline cannot silently claim success', async () => {
  let wall = 29_999;
  let elapsed = 0;
  await assert.rejects(freshTotpStep(0, { now: () => wall, monotonic: () => elapsed,
    sleep: async () => { wall = 90_000; elapsed = 32_000; } }), /bounded wait/);
});

test('fresh step computation never selects a future window code', async () => {
  const fake = clock(30_150);
  assert.equal(await freshTotpStep(0, fake.options), currentTotpStep(30_150));
  assert.equal(fake.waits.length, 0);
});

test('invalid counters, clocks and unbounded waits are rejected', async () => {
  for (const value of [false, '1', -2, 0.5, NaN, Infinity]) {
    await assert.rejects(freshTotpStep(value), /Invalid/);
  }
  for (const value of [NaN, Infinity, -1]) assert.throws(() => currentTotpStep(value), /Invalid/);
  for (const options of [{ timeoutMs: 60_000 }, { timeoutMs: 0 }, { settleMs: 1000 }]) {
    await assert.rejects(freshTotpStep(1, options), /Invalid/);
  }
});
