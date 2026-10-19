// Where a name in a list leads. Records with a page of their own open it; tenants open their party
// file over the current page; records without a page open their list filtered to them (?suche=).
const TARGETS = {
  property: id => `/properties/${encodeURIComponent(id)}`,
  unit: id => `/units/${encodeURIComponent(id)}`,
  maintenance: id => `/maintenance/${encodeURIComponent(id)}`,
  serviceContract: id => `/service-contracts/${encodeURIComponent(id)}`,
  invoiceReview: id => `/invoice-review/${encodeURIComponent(id)}`,
  tenantAccount: id => `/tenants/${encodeURIComponent(id)}/account`,
  contract: id => `/contracts?contract_id=${encodeURIComponent(id)}`,
  booking: id => `/bookings?booking_id=${encodeURIComponent(id)}`,
  invoice: id => `/invoices?focus_id=${encodeURIComponent(id)}`,
  document: id => `/documents?focus_id=${encodeURIComponent(id)}`,
  task: id => `/tasks?focus_id=${encodeURIComponent(id)}`,
  receivable: id => `/receivables?focus_id=${encodeURIComponent(id)}`,
  contact: id => `/contacts?focus_id=${encodeURIComponent(id)}`,
  dunningCase: id => `/dunning/contracts/${encodeURIComponent(id)}`,
};
const SEARCH_TARGETS = {
  contact: '/contacts',
  contract: '/contracts',
  lead: '/leads',
  account: '/bookings',
  invoice: '/invoices',
};

export function entityHref(kind, id, text) {
  if (TARGETS[kind] && id) return TARGETS[kind](id);
  if (SEARCH_TARGETS[kind] && text) return `${SEARCH_TARGETS[kind]}?suche=${encodeURIComponent(text)}`;
  return null;
}
