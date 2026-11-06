import { entityHref } from '../../utils/entityLinks';
import { safeInternalHref } from '../../utils/internalLinks';

// A supplied internal URL may carry useful tabs and receipt context. For
// known records it must still identify the card's actual kind and ID.
const IDENTITIES = {
  property: ['/properties', []], unit: ['/units', []], maintenance: ['/maintenance', []],
  service_contract: ['/service-contracts', []], serviceContract: ['/service-contracts', []],
  invoiceReview: ['/invoice-review', []], document: ['/documents', ['focus_id']],
  task: ['/tasks', ['focus_id']], contract: ['/contracts', ['contract_id', 'focus_id']],
  booking: ['/bookings', ['booking_id', 'focus_id']], receivable: ['/receivables', ['focus_id']],
  tenant: ['/tenants', ['focus_id']], contact: ['/contacts', ['focus_id']],
  account: ['/accounts', ['focus_id']], lead: ['/leads', ['focus_id']],
  invoice: ['/invoices', ['focus_id']],
  meter: ['/meters', ['focus_id']], calendar: ['/calendar', ['focus_id']],
  portfolio: ['/portfolios', ['focus_id']], billing_period: ['/statements', ['period_id', 'focus_id']],
  utility_statement: ['/statements', ['statement_id', 'focus_id']], standalone_reading: ['/meters', ['source_id']],
};
function identifies(card, href) {
  const rule = IDENTITIES[card.kind];
  if (!rule || !card.id) return true;
  const url = new URL(href, 'https://workspace.invalid');
  const [path, keys] = rule;
  if (card.kind === 'invoice' && url.pathname === `/invoice-review/${encodeURIComponent(card.id)}`) return true;
  if ((!keys.length || card.kind === 'document') && url.pathname === `${path}/${encodeURIComponent(card.id)}`) return true;
  if (url.pathname !== path) return false;
  if (card.kind === 'standalone_reading' && (!url.searchParams.get('focus_id') || (card.values?.meter_id && url.searchParams.get('focus_id') !== String(card.values.meter_id)))) return false;
  const selected = keys.filter(key => url.searchParams.has(key));
  return selected.length > 0 && selected.every(key => url.searchParams.getAll(key).every(value => value === String(card.id)));
}

export function contextHref(card) {
  const provided = safeLocalHref(card.href); if (provided && identifies(card, provided)) return provided;
  if (!card.id) return '';
  if (card.kind === 'standalone_reading') return card.values?.meter_id
    ? `/meters?focus_id=${encodeURIComponent(card.values.meter_id)}&source_id=${encodeURIComponent(card.id)}` : '';
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
  return /^\/(properties|units|tenants|contacts|documents|invoices|invoice-review|contracts|bookings|reports|maintenance|tasks|service-contracts|statements|receivables|meters|calendar|portfolios|handover-protocols|assistant|work-center|rent-overview|dunning|accounts|leads)(\/|\?|#|$)/.test(value) ? value : '';
}
