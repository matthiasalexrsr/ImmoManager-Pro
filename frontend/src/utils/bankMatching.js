import { centsInput, storedCents } from './accountMoney';

const kinds = ['invoice', 'receivable', 'rent_charge'];
const day = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value);
const cents = value => Number.isSafeInteger(value) && value >= 0;
const identity = value => typeof value === 'string' && value.length > 0 && value.length <= 100;
function envelope(value) {
  if (!Array.isArray(value?.items) || value.items.length > 25 || typeof value.has_more !== 'boolean'
    || (value.has_more ? typeof value.next_cursor !== 'string' || !value.next_cursor : value.next_cursor !== null)) throw new Error('bankMatching.invalidResponse');
  return value;
}
export function checkedSuggestions(value, bookingId, kind) {
  envelope(value);
  if (value.booking_id !== bookingId || !cents(value.available_cents) || typeof value.ambiguous !== 'boolean') throw new Error('bankMatching.invalidResponse');
  value.items.forEach(item => {
    if (item.kind !== kind || !identity(item.id) || typeof item.label !== 'string' || !day(item.due_date)
      || (item.reference !== null && typeof item.reference !== 'string') || (item.property_label !== null && typeof item.property_label !== 'string')
      || !cents(item.open_cents) || !cents(item.suggested_cents) || item.suggested_cents <= 0 || item.suggested_cents > item.open_cents
      || item.suggested_cents > value.available_cents || typeof item.review_token !== 'string' || !item.review_token
      || !Array.isArray(item.reasons) || item.reasons.some(reason => !['reference', 'amount_exact', 'same_portfolio', 'unassigned_property', 'assigned_property', 'partial_payment'].includes(reason))) throw new Error('bankMatching.invalidResponse');
  });
  return value;
}
export function checkedPayments(value) {
  envelope(value);
  value.items.forEach(item => {
    const amount = storedCents(item.amount);
    if (!identity(item.id) || !identity(item.entity_id) || !kinds.includes(item.entity_type) || !day(item.payment_date)
      || amount === null || BigInt(amount) <= 0n || (item.reversal && (item.reversal.payment_id !== item.id
        || !identity(item.reversal.id) || typeof item.reversal.reason !== 'string' || !day(item.reversal.reversal_date)
        || storedCents(item.reversal.amount) !== amount))) throw new Error('bankMatching.invalidResponse');
  });
  return value;
}
export function exactAmount(value, maximumCents) {
  if (typeof value !== 'string' || !/^\d+(?:[.,]\d{1,2})?$/.test(value)) return null;
  const amount = storedCents(value.replace(',', '.'));
  if (amount === null || BigInt(amount) <= 0n || BigInt(amount) > BigInt(maximumCents)) return null;
  return centsInput(amount);
}
export const paymentPath = type => ({ invoice: 'invoices', rent_charge: 'rent-charges', receivable: 'receivables' })[type];
export function checkedReversal(value, receipt, request) {
  if (!identity(value?.id) || value.payment_id !== receipt.id || storedCents(value.amount) !== storedCents(receipt.amount)
    || value.reversal_date !== request.reversal_date || value.reason !== request.reason || value.idempotency_key !== request.idempotency_key) throw new Error('bankMatching.invalidResponse');
  return value;
}
