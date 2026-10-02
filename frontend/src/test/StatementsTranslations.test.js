import { describe, expect, it } from 'vitest';
import de from '../../../i18n/de-DE.json';
import en from '../../../i18n/en-US.json';
import es from '../../../i18n/es-ES.json';

const requiredKeys = [
  'pages.statements.stepCreate', 'pages.statements.stepCosts',
  'pages.statements.stepPreflight', 'pages.statements.stepGenerate',
  'pages.statements.stepFinalize', 'pages.statements.stepDeliver',
  'ui.buttons.retry', 'ui.form.status',
];

describe('Statements recovery and workflow translations', () => {
  it.each([['de-DE', de], ['en-US', en], ['es-ES', es]])('provides readable labels in %s', (_locale, messages) => {
    for (const key of requiredKeys) {
      const label = key.split('.').reduce((value, part) => value?.[part], messages);
      expect(label, key).toEqual(expect.any(String));
      expect(label.trim(), key).not.toBe('');
      expect(label, key).not.toBe(key);
    }
  });
});
