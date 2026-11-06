// Real-clock fixture coordination only. Never alter the application's clock,
// OTP verification window or replay policy to make a browser test pass.
import { performance } from 'node:perf_hooks';

export const TOTP_STEP_MS = 30_000;

export function currentTotpStep(milliseconds = Date.now()) {
  if (!Number.isFinite(milliseconds) || milliseconds < 0) throw new TypeError('Invalid real clock value');
  return Math.floor(milliseconds / TOTP_STEP_MS);
}

export async function freshTotpStep(lastSubmittedStep, {
  now = Date.now,
  monotonic = () => performance.now(),
  sleep = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds)),
  timeoutMs = 31_000,
  settleMs = 150,
} = {}) {
  if (!Number.isSafeInteger(lastSubmittedStep) || lastSubmittedStep < -1
      || !Number.isFinite(timeoutMs) || timeoutMs <= 0 || timeoutMs > 31_000
      || !Number.isFinite(settleMs) || settleMs < 0 || settleMs >= 1000) {
    throw new TypeError('Invalid bounded TOTP wait configuration');
  }
  const started = monotonic();
  for (;;) {
    const elapsed = monotonic() - started;
    if (!Number.isFinite(elapsed) || elapsed < 0 || elapsed >= timeoutMs) {
      throw new Error('A fresh real TOTP step was not reached within the bounded wait');
    }
    const wall = now();
    const step = currentTotpStep(wall);
    if (step > lastSubmittedStep && wall - step * TOTP_STEP_MS >= settleMs) return step;
    const target = Math.max(lastSubmittedStep + 1, step) * TOTP_STEP_MS + settleMs;
    await sleep(Math.min(Math.max(1, target - wall), timeoutMs - elapsed));
  }
}
