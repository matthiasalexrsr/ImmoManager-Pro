import { api } from '../../api';
import { yearWindow } from './model';

const collection = value => {
  if (!Array.isArray(value)) throw new Error('Die Auswahldaten konnten nicht vollständig gelesen werden.');
  return value;
};

async function paymentCandidates(base, year, signal) {
  const found = [], seen = new Set();
  let total = null;
  while (true) {
    if (signal.aborted) throw new DOMException('Abgebrochen', 'AbortError');
    const query = new URLSearchParams({ ...yearWindow(year), skip: String(found.length), limit: '200' });
    const page = await api.get(`${base}/payment-candidates?${query}`, { signal });
    if (!page || !Array.isArray(page.items) || !Number.isSafeInteger(page.total) || page.total < 0 || typeof page.has_more !== 'boolean') {
      throw new Error('Die Zahlungsvorschläge konnten nicht vollständig gelesen werden. Bitte erneut laden.');
    }
    if (total !== null && total !== page.total) throw new Error('Die Zahlungsvorschläge haben sich geändert. Bitte erneut laden.');
    total = page.total;
    for (const row of page.items) {
      if (!row?.booking_id || seen.has(row.booking_id)) throw new Error('Die Zahlungsvorschläge haben sich geändert. Bitte erneut laden.');
      seen.add(row.booking_id); found.push(row);
    }
    if (found.length > total || (page.has_more && (!page.items.length || found.length >= total))) {
      throw new Error('Die Zahlungsvorschläge sind unvollständig. Bitte erneut laden.');
    }
    if (!page.has_more) {
      if (found.length !== total) throw new Error('Die Zahlungsvorschläge sind unvollständig. Bitte erneut laden.');
      return found;
    }
  }
}

export async function financeChoices(kind, base, propertyIds, year, signal) {
  const options = { signal }, allowed = new Set(propertyIds);
  if (kind === 'payment') return { candidates: await paymentCandidates(base, year, signal) };
  if (kind === 'existingBill') {
    const invoices = collection(await api.list('/invoices', options));
    return { invoices: invoices.filter(invoice => !invoice.property_id || allowed.has(invoice.property_id)) };
  }
  const [periods, keys, properties] = await Promise.all([
    api.list('/billing/periods', options), api.list('/billing/allocation-keys', options), api.list('/properties', options),
  ]);
  return {
    periods: collection(periods).filter(period => allowed.has(period.property_id) && ['draft', 'review'].includes(period.status)),
    keys: collection(keys), names: Object.fromEntries(collection(properties).map(property => [property.id, property.name])),
  };
}
