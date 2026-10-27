import { expect, it, vi } from 'vitest';
import { RELOAD_KEY, currentEntry, recoverFromMissingPart } from '../buildRecovery';

const memory = () => {
  const values = new Map();
  return { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, String(value)) };
};
const page = entry => `<!doctype html><html><head><script type="module" crossorigin src="${entry}"></script></head></html>`;
const failure = new TypeError('Failed to fetch dynamically imported module');
const settled = promise => Promise.race([promise.then(() => 'resolved', () => 'rejected'),
  new Promise(resolve => setTimeout(() => resolve('pending'), 20))]);

function setup(served, { storage = memory(), clock = 1_000_000, leaving = false } = {}) {
  const location = { reload: vi.fn() };
  const options = {
    fetchPage: vi.fn(async () => served), entry: '/assets/index-Old11111.js', location, storage,
    now: () => clock, isLeaving: () => leaving,
  };
  return { options, location, storage };
}

it('loads the current version once when the server names a newer entry, and stays loading', async () => {
  const { options, location, storage } = setup(page('/assets/index-New22222.js'));
  expect(await settled(recoverFromMissingPart(failure, options))).toBe('pending');
  expect(location.reload).toHaveBeenCalledOnce();
  expect(storage.getItem(RELOAD_KEY)).toBe('1000000');
});

it('passes a failure of the same version on to the error boundary', async () => {
  const { options, location } = setup(page('/assets/index-Old11111.js'));
  await expect(recoverFromMissingPart(failure, options)).rejects.toBe(failure);
  options.fetchPage.mockRejectedValueOnce(new TypeError('offline'));
  await expect(recoverFromMissingPart(failure, options)).rejects.toBe(failure);
  expect(location.reload).not.toHaveBeenCalled();
});

it('treats a fetch aborted by leaving the page as no error and does not reload', async () => {
  const { options, location } = setup(page('/assets/index-New22222.js'), { leaving: true });
  expect(await settled(recoverFromMissingPart(failure, options))).toBe('pending');
  expect(options.fetchPage).not.toHaveBeenCalled();
  expect(location.reload).not.toHaveBeenCalled();
});

it('does not reload in a loop, nor without storage for the guard', async () => {
  const storage = memory();
  storage.setItem(RELOAD_KEY, String(1_000_000 - 5_000));
  const recent = setup(page('/assets/index-New22222.js'), { storage });
  await expect(recoverFromMissingPart(failure, recent.options)).rejects.toBe(failure);
  const none = setup(page('/assets/index-New22222.js'), { storage: null });
  await expect(recoverFromMissingPart(failure, none.options)).rejects.toBe(failure);
  expect(recent.location.reload).not.toHaveBeenCalled();
  expect(none.location.reload).not.toHaveBeenCalled();
});

it('finds the built entry of the running page', () => {
  const doc = new DOMParser().parseFromString(page('/assets/index-Old11111.js'), 'text/html');
  expect(currentEntry(doc)).toBe('/assets/index-Old11111.js');
  expect(currentEntry(new DOMParser().parseFromString('<script type="module" src="/src/main.jsx"></script>', 'text/html'))).toBe(null);
});
