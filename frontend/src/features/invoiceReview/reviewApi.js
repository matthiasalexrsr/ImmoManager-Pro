import { api } from '../../api';
import { formatMoney } from '../../utils/format';
import { fill } from './text';

const enc = encodeURIComponent;
const base = invoiceId => `/invoices/${enc(invoiceId)}/review`;

export function query(params) {
  const search = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '' && value !== false) search.set(key, String(value));
  });
  const text = search.toString();
  return text ? `?${text}` : '';
}

// only the fields that carry a value; numbers from form inputs become numbers
export function compact(values) {
  return Object.fromEntries(Object.entries(values || {}).filter(([, value]) => value !== '' && value !== undefined
    && value !== null));
}

export const reviewApi = {
  inbox: (params, options) => api.get(`/invoice-review/inbox${query(params)}`, options),
  proposals: (params, options) => api.get(`/invoice-review/payment-proposals${query(params)}`, options),
  duplicates: (params, options) => api.get(`/invoice-review/duplicates${query(params)}`, options),
  settings: options => api.get('/invoice-review/settings', options),
  saveSettings: values => api.put('/invoice-review/settings', values),
  newReceipt: values => api.post('/invoice-review/receipts', values),
  load: (invoiceId, options) => api.get(base(invoiceId), options),
  receive: (invoiceId, values) => api.post(base(invoiceId), values),
  patch: (invoiceId, values) => api.patch(base(invoiceId), values),
  check: (invoiceId, kind, values) => api.post(`${base(invoiceId)}/${kind}-check`, values),
  decide: (invoiceId, values) => api.post(`${base(invoiceId)}/decision`, values),
  resolve: (invoiceId, values) => api.post(`${base(invoiceId)}/dispute`, values),
  transfer: (invoiceId, values) => api.post(`${base(invoiceId)}/cost-transfer`, values),
  paymentCandidates: (invoiceId, options) => api.get(`/invoices/${enc(invoiceId)}/payments/candidates`, options),
  addPayment: (invoiceId, values) => api.post(`/invoices/${enc(invoiceId)}/payments`, values),
};

const MONEY_PARAMS = new Set(['expected', 'actual', 'vat', 'net', 'difference', 'ordered', 'billed', 'billed_elsewhere',
  'change_order', 'planned', 'credited', 'paid', 'gross']);

// A finding in the reader's language; the server's German message when the code is unknown.
export function findingText(tx, finding) {
  const template = tx[`f_${finding.code}`];
  if (!template) return finding.message;
  const params = Object.fromEntries(Object.entries(finding.params || {}).map(([key, value]) => {
    if (MONEY_PARAMS.has(key) && typeof value === 'number') return [key, formatMoney(value)];
    if (key === 'field') return [key, tx[`cl_${value}`] || value];
    return [key, value ?? '—'];
  }));
  return fill(template, params);
}

export const STATUS_TONE = {
  legacy: 'gray', received: 'blue', query: 'orange', approved: 'green', partially_approved: 'orange', rejected: 'red',
};
export const PAYMENT_TONE = {
  open: 'blue', partially_paid: 'orange', paid: 'green', overpaid: 'red', not_payable: 'gray', rejected: 'red',
  credit_note: 'gray',
};
