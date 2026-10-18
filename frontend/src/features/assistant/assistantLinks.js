export function contextHref(card) {
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
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//') || value.includes('\\') || [...value].some(character => character.charCodeAt(0) < 32)) return '';
  return /^\/(properties|units|tenants|contacts|documents|invoice-review|contracts|bookings|reports|maintenance|tasks|service-contracts|statements|receivables|assistant|work-center|rent-overview|dunning)(\/|\?|#|$)/.test(value) ? value : '';
}
