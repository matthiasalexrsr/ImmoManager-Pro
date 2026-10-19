import { entityHref } from '../../utils/entityLinks';
import { safeInternalHref } from '../../utils/internalLinks';

export function contextHref(card) {
  const provided = safeLocalHref(card.href); if (provided) return provided;
  if (!card.id) return '';
  const kind = { service_contract: 'serviceContract' }[card.kind] || card.kind;
  const exact = entityHref(kind, card.id);
  if (exact) return exact;
  const id = encodeURIComponent(card.id);
  return card.kind === 'property' ? `/properties/${id}` : card.kind === 'unit' ? `/units/${id}`
    : card.kind === 'tenant' ? `/tenants?focus_id=${id}` : card.kind === 'contact' ? `/contacts?focus_id=${id}`
      : card.kind === 'document' ? `/documents?focus_id=${id}` : '';
}
export function reportHref(report) {
  const params = new URLSearchParams(Object.entries(report || {}).filter(([key, value]) => ['kind', 'as_of', 'date_from', 'date_to', 'property_id', 'unit_id'].includes(key) && value));
  return `/reports?${params}`;
}
export function safeLocalHref(value) {
  if (!safeInternalHref(value)) return '';
  return /^\/(properties|units|tenants|contacts|documents|invoices|invoice-review|contracts|bookings|reports|maintenance|tasks|service-contracts|statements|receivables|meters|calendar|portfolios|handover-protocols|assistant|work-center|rent-overview|dunning)(\/|\?|#|$)/.test(value) ? value : '';
}
