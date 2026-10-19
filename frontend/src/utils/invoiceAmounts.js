/** VAT and gross follow net and rate while neither was entered by hand (the server checks gross = net + VAT). */
export function deriveAmounts(values, changed, touched) {
  if (!['net_amount', 'vat_rate'].includes(changed) || touched.has('vat_amount') || touched.has('gross_amount')) return {};
  const net = Number(values.net_amount);
  const rate = Number(values.vat_rate);
  if (values.net_amount === '' || values.net_amount == null || values.vat_rate === '' || values.vat_rate == null
      || !Number.isFinite(net) || !Number.isFinite(rate)) return {};
  const netCents = Math.round(Number((net * 100).toFixed(6)));
  const vatCents = Math.round(Number((netCents * rate / 100).toFixed(6)));
  return { vat_amount: (vatCents / 100).toFixed(2), gross_amount: ((netCents + vatCents) / 100).toFixed(2) };
}
