import { afterEach, expect, it, vi } from 'vitest';
import { RELOAD_KEY, installBuildRecovery } from '../buildRecovery';

const memory = () => {
  const values = new Map();
  return { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, String(value)) };
};

function page() {
  const target = new EventTarget();
  target.location = { reload: vi.fn() };
  return target;
}

function failedChunk(target) {
  const event = new Event('vite:preloadError', { cancelable: true });
  event.payload = new TypeError('Failed to fetch dynamically imported module');
  target.dispatchEvent(event);
  return event;
}

let uninstall = () => {};
afterEach(() => uninstall());

it('loads the current version once when a part of the old one is gone', () => {
  const target = page(), storage = memory();
  uninstall = installBuildRecovery(target, storage, () => 1_000_000);
  const event = failedChunk(target);
  expect(event.defaultPrevented).toBe(true);
  expect(target.location.reload).toHaveBeenCalledOnce();
  expect(storage.getItem(RELOAD_KEY)).toBe('1000000');
});

it('leaves a repeated failure to the error boundary instead of reloading in a loop', () => {
  const target = page(), storage = memory();
  let clock = 1_000_000;
  uninstall = installBuildRecovery(target, storage, () => clock);
  failedChunk(target);
  clock += 5_000;
  const again = failedChunk(target);
  expect(again.defaultPrevented).toBe(false);
  expect(target.location.reload).toHaveBeenCalledOnce();
  clock += 120_000;
  expect(failedChunk(target).defaultPrevented).toBe(true);
  expect(target.location.reload).toHaveBeenCalledTimes(2);
});

it('does not reload without storage for the loop guard', () => {
  const target = page();
  uninstall = installBuildRecovery(target, null);
  expect(failedChunk(target).defaultPrevented).toBe(false);
  const blocked = { getItem: () => { throw new Error('blocked'); }, setItem: () => {} };
  uninstall();
  uninstall = installBuildRecovery(target, blocked);
  expect(failedChunk(target).defaultPrevented).toBe(false);
  expect(target.location.reload).not.toHaveBeenCalled();
});
