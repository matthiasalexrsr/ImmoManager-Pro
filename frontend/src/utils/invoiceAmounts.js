/** VAT and gross follow net and rate while neither was entered by hand (the server checks gross = net + VAT). */
const halfUp = value => Math.sign(value) * Math.round(Number(Math.abs(value).toFixed(6)));

export function deriveAmounts(values, changed, touched) {
  if (!['net_amount', 'vat_rate'].includes(changed) || touched.has('vat_amount') || touched.has('gross_amount')) return {};
  const net = Number(values.net_amount);
  const rate = Number(values.vat_rate);
  if (values.net_amount === '' || values.net_amount == null || values.vat_rate === '' || values.vat_rate == null
      || !Number.isFinite(net) || !Number.isFinite(rate)) return {};
  const netCents = halfUp(net * 100);
  const vatCents = halfUp(netCents * rate / 100);
  return { vat_amount: (vatCents / 100).toFixed(2), gross_amount: ((netCents + vatCents) / 100).toFixed(2) };
}
