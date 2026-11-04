import { describe, expect, it } from 'vitest';
import { initializeIntegrationValues, isDefiniteIntegrationFailure, serializeIntegrationValues } from '../utils/integrationFields';

describe('integration field API contract', () => {
  const fields = [
    { key: 'messages', label: 'Nachrichten', type: 'array', required: true },
    { key: 'context', label: 'Kontext', type: 'object' },
    { key: 'fraction', label: 'Anteil', type: 'number', min: 0, max: 2, required: true },
    { key: 'batch', label: 'Abschnitt', type: 'integer', options: [0, 2], default: 0, required: true },
    { key: 'sandbox', label: 'Sandbox', type: 'boolean', default: false, required: true },
    { key: 'optional', label: 'Optional', type: 'number' },
  ];

  it('serializes JSON, decimals, numeric options, zero and false using the advertised types', () => {
    const defaults = initializeIntegrationValues(fields);
    expect(defaults).toEqual({ batch: 0, sandbox: false });
    expect(serializeIntegrationValues(fields, { ...defaults, messages: '[{"body":"Prüfung"}]', context: '{"tenant":0}', fraction: '0.25', batch: '2', optional: '' }))
      .toEqual({ messages: [{ body: 'Prüfung' }], context: { tenant: 0 }, fraction: 0.25, batch: 2, sandbox: false });
  });

  it('round trips editable structured defaults and never initializes a secret mask as a replacement', () => {
    const schema = [{ key: 'headers', type: 'object', default: { level: 2 } }, { key: 'token', type: 'string', secret: true, required: true }];
    const draft = initializeIntegrationValues(schema, { token: '***' });
    expect(JSON.parse(draft.headers)).toEqual({ level: 2 });
    expect(serializeIntegrationValues(schema, draft, { retainedSecrets: ['token'] })).toEqual({ headers: { level: 2 } });
    expect(() => serializeIntegrationValues(schema, draft)).toThrow('token: Bitte ausfüllen.');
  });

  it.each([
    ['broken JSON', { key: 'messages', label: 'Nachrichten', type: 'array', required: true }, '{'],
    ['object where an array is required', { key: 'messages', label: 'Nachrichten', type: 'array' }, '{}'],
    ['array where an object is required', { key: 'messages', label: 'Nachrichten', type: 'object' }, '[]'],
    ['null object', { key: 'messages', label: 'Nachrichten', type: 'object' }, 'null'],
    ['empty required numeric input', { key: 'messages', label: 'Nachrichten', type: 'number', required: true }, '   '],
    ['empty required string', { key: 'messages', label: 'Nachrichten', type: 'string', required: true }, '\t  '],
    ['fractional integer', { key: 'messages', label: 'Nachrichten', type: 'integer' }, '1.5'],
    ['unsafe integer', { key: 'messages', label: 'Nachrichten', type: 'integer' }, '9007199254740993'],
    ['nonfinite number', { key: 'messages', label: 'Nachrichten', type: 'number' }, 'Infinity'],
    ['out of range number', { key: 'messages', label: 'Nachrichten', type: 'number', max: 20 }, 21],
    ['unknown option', { key: 'messages', label: 'Nachrichten', type: 'integer', options: [0, 2] }, 1],
  ])('rejects %s with the affected field name', (_, field, value) => {
    expect(() => serializeIntegrationValues([field], { messages: value })).toThrow(/^Nachrichten:/);
  });

  it('can explicitly clear nonsecret config fields while preserving secret blanks and omitting action blanks', () => {
    const schema = [{ key: 'count', type: 'number' }, { key: 'name', type: 'string' }, { key: 'token', type: 'string', secret: true }];
    const draft = { count: '  ', name: '', token: '' };
    expect(serializeIntegrationValues(schema, draft)).toEqual({});
    expect(serializeIntegrationValues(schema, draft, { emptyValue: null })).toEqual({ count: null, name: null });
  });

  it('preserves zero and false even when a select submitted strings', () => {
    const schema = [{ key: 'zero', type: 'integer', required: true, options: [0, 1] },
      { key: 'false', type: 'boolean', required: true, options: [false, true] }];
    expect(serializeIntegrationValues(schema, { zero: '0', false: 'false' })).toEqual({ zero: 0, false: false });
  });

  it('treats 413 as rejection and retains network/server uncertainty', () => {
    expect(isDefiniteIntegrationFailure({ statusCode: 413 })).toBe(true);
    expect(isDefiniteIntegrationFailure({ statusCode: 409 })).toBe(true);
    expect(isDefiniteIntegrationFailure({ statusCode: 503 })).toBe(false);
    expect(isDefiniteIntegrationFailure(new TypeError('network'))).toBe(false);
  });
});
