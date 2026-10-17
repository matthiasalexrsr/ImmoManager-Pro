import { expect, it } from 'vitest';
import { fieldValidationErrors } from '../utils/formValidationFeedback';

const fields = [
  { key: 'amount', type: 'number' }, { key: 'notes', type: 'textarea' },
  { key: 'secret_field', type: 'hidden' },
];

it('maps only known top-level FastAPI body errors and keeps all messages for a field', () => {
  const error = { statusCode: 422, details: [
    { loc: ['body', 'amount'], msg: 'Value error, Betrag ungültig' },
    { loc: ['body', 'amount'], msg: 'Betrag zu groß' },
    { loc: ['query', 'notes'], msg: 'Notizen nur in Query' },
    { loc: ['body', 'other'], msg: 'unbekannt' },
    { loc: ['body', 'notes', 0], msg: 'nested' },
    { loc: ['body', 'secret_field'], msg: 'unsichtbar' },
  ] };
  expect(fieldValidationErrors(error, fields)).toEqual({ amount: ['Betrag ungültig', 'Betrag zu groß'] });
});

it('supports documented structured validation details but ignores non-field objects', () => {
  expect(fieldValidationErrors({ statusCode: 400, details: [
    { field: 'notes', message: 'Bitte prüfen' },
    { field: 'amount', msg: 'Zahl fehlt' },
    { field: 'nested.amount', message: 'nicht zuordnen' },
    { field: 'secret_field', message: 'hidden' },
    { field: 'amount', message: '' },
    { field: 'notes', message: 12 },
    null,
  ] }, fields)).toEqual({ notes: ['Bitte prüfen'], amount: ['Zahl fehlt'] });
  expect(fieldValidationErrors({ statusCode: 500, details: [{ field: 'amount', message: 'Intern' }] }, fields)).toEqual({});
  expect(fieldValidationErrors({ statusCode: 422, details: { amount: 'Nein' } }, fields)).toEqual({});
  expect(fieldValidationErrors(null, fields)).toEqual({});
});
