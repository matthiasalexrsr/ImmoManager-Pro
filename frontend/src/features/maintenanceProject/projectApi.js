import { api } from '../../api';

const enc = encodeURIComponent;
const base = caseId => `/maintenance/${enc(caseId)}`;
// FormModal adds the state it opened (updated_at); the project endpoints accept only their own fields.
const body = values => Object.fromEntries(Object.entries(values || {}).filter(([key]) => key !== 'updated_at'));
const query = params => {
  const search = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value));
  });
  const text = search.toString();
  return text ? `?${text}` : '';
};

export const projectApi = {
  load: (caseId, options) => api.get(`${base(caseId)}/project`, options),
  updateCase: (caseId, values) => api.patch(base(caseId), values),
  transition: (caseId, values) => api.post(`${base(caseId)}/transition`, body(values)),

  addPackage: (caseId, values) => api.post(`${base(caseId)}/work-packages`, body(values)),
  updatePackage: (caseId, id, values) => api.patch(`${base(caseId)}/work-packages/${enc(id)}`, body(values)),
  deletePackage: (caseId, id) => api.del(`${base(caseId)}/work-packages/${enc(id)}`),
  addDependency: (caseId, values) => api.post(`${base(caseId)}/dependencies`, body(values)),
  deleteDependency: (caseId, id) => api.del(`${base(caseId)}/dependencies/${enc(id)}`),

  addParticipant: (caseId, values) => api.post(`${base(caseId)}/participants`, body(values)),
  deleteParticipant: (caseId, id) => api.del(`${base(caseId)}/participants/${enc(id)}`),
  addAppointment: (caseId, values) => api.post(`${base(caseId)}/appointments`, body(values)),
  updateAppointment: (caseId, id, values) => api.patch(`${base(caseId)}/appointments/${enc(id)}`, body(values)),
  deleteAppointment: (caseId, id) => api.del(`${base(caseId)}/appointments/${enc(id)}`),

  addQuote: (caseId, values) => api.post(`${base(caseId)}/quotes`, body(values)),
  updateQuote: (caseId, id, values) => api.patch(`${base(caseId)}/quotes/${enc(id)}`, body(values)),
  deleteQuote: (caseId, id) => api.del(`${base(caseId)}/quotes/${enc(id)}`),
  acceptQuote: (caseId, id, values) => api.post(`${base(caseId)}/quotes/${enc(id)}/accept`, body(values)),
  rejectQuote: (caseId, id, values) => api.post(`${base(caseId)}/quotes/${enc(id)}/reject`, body(values)),
  cancelOrder: (caseId, id, values) => api.post(`${base(caseId)}/orders/${enc(id)}/cancel`, body(values)),
  completeOrder: (caseId, id) => api.post(`${base(caseId)}/orders/${enc(id)}/complete`, {}),
  addChangeOrder: (caseId, orderId, values) => api.post(`${base(caseId)}/orders/${enc(orderId)}/change-orders`, body(values)),
  deleteChangeOrder: (caseId, id) => api.del(`${base(caseId)}/change-orders/${enc(id)}`),
  approveChangeOrder: (caseId, id, values) => api.post(`${base(caseId)}/change-orders/${enc(id)}/approve`, body(values)),
  rejectChangeOrder: (caseId, id, values) => api.post(`${base(caseId)}/change-orders/${enc(id)}/reject`, body(values)),

  linkInvoice: (caseId, orderId, values) => api.post(`${base(caseId)}/orders/${enc(orderId)}/invoices`, body(values)),
  unlinkInvoice: (caseId, linkId) => api.del(`${base(caseId)}/invoice-links/${enc(linkId)}`),
  invoiceCandidates: (caseId, params, options) => api.get(`${base(caseId)}/invoice-candidates${query(params)}`, options),
  paymentCandidates: (invoiceId, params, options) =>
    api.get(`/invoices/${enc(invoiceId)}/payments/candidates${query(params)}`, options),
  addPayment: (invoiceId, values) => api.post(`/invoices/${enc(invoiceId)}/payments`, body(values)),
  deletePayment: (invoiceId, id) => api.del(`/invoices/${enc(invoiceId)}/payments/${enc(id)}`),

  addProtocol: (caseId, values) => api.post(`${base(caseId)}/protocols`, body(values)),
  updateProtocol: (caseId, id, values) => api.patch(`${base(caseId)}/protocols/${enc(id)}`, body(values)),
  deleteProtocol: (caseId, id) => api.del(`${base(caseId)}/protocols/${enc(id)}`),
  finalizeProtocol: (caseId, id, idempotencyKey) =>
    api.post(`${base(caseId)}/protocols/${enc(id)}/finalize`, { idempotency_key: idempotencyKey }),
  protocolPdf: (caseId, id, options) => api.getBlob(`${base(caseId)}/protocols/${enc(id)}/pdf`, options),

  linkDocument: (caseId, values) => api.post(`${base(caseId)}/documents`, body(values)),
  unlinkDocument: (caseId, id) => api.del(`${base(caseId)}/documents/${enc(id)}`),
  propertyDocuments: (propertyId, options) => api.list(`/documents?property_id=${enc(propertyId)}`, options),
  contacts: options => api.list('/contacts', options),
};

export function commandKey(prefix) {
  const random = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${random}`.replace(/[^A-Za-z0-9._:-]/g, '-').slice(0, 100);
}
