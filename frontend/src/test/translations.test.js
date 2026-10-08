import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

// t('some.key') returns the key itself when a text is missing, so `t(key) || 'Fallback'`
// never falls back: a missing text shows up as "pages.settings.tabSystem" in the UI.
const SRC = path.resolve(__dirname, '..');
const LOCALES = ['de-DE', 'en-US', 'es-ES'];
const KEY = /\b(?:t|tr)\(\s*(['"])([A-Za-z0-9_.-]+)\1/g;  // tr: local helpers and aliases of t

function sourceFiles(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === 'test' ? [] : sourceFiles(full);
    return /\.jsx?$/.test(entry.name) && !entry.name.includes('.test.') ? [full] : [];
  });
}

function text(tree, key) {
  const value = key.split('.').reduce((node, part) => (node && typeof node === 'object' ? node[part] : undefined), tree);
  return typeof value === 'string' ? value : undefined;
}

const usedKeys = new Map();
for (const file of sourceFiles(SRC)) {
  for (const match of fs.readFileSync(file, 'utf8').matchAll(KEY)) {
    if (!usedKeys.has(match[2])) usedKeys.set(match[2], path.relative(SRC, file));
  }
}

describe('translations', () => {
  it('finds the keys the UI uses', () => {
    expect(usedKeys.size).toBeGreaterThan(500);
  });

  it.each(LOCALES)('%s has a text for every key the UI uses', (locale) => {
    const tree = JSON.parse(fs.readFileSync(path.resolve(SRC, '../../i18n', `${locale}.json`), 'utf8'));
    const missing = [...usedKeys].filter(([key]) => text(tree, key) === undefined).map(([key, file]) => `${key} (${file})`);

    expect(missing).toEqual([]);
  });
});
