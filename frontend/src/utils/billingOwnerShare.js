const invalid = () => Object.assign(new Error('Invalid owner cost share response'), { code: 'INVALID_OWNER_SHARE' });
const id = value => typeof value === 'string' && value.trim().length > 0;
const moneyKeys = ['total_amount', 'recoverable_vacancy_amount', 'non_recoverable_amount',
  'property_cost_total', 'tenant_cost_total'];
function cents(value) {
  if (!['number', 'string'].includes(typeof value) || String(value).trim() === '') throw invalid();
  const amount = Number(value) * 100;
  if (!Number.isSafeInteger(Math.round(amount)) || Math.abs(amount - Math.round(amount)) > 0.000001) throw invalid();
  return Math.round(amount);
}

/** The server owns allocation; the UI only verifies the saved snapshot's totals. */
export function parseOwnerCostShare(body, periodId) {
  if (body?.id !== periodId || !Object.hasOwn(body, 'owner_cost_share')) throw invalid();
  const share = body.owner_cost_share;
  if (share === null) return null;
  if (!share || !Array.isArray(share.line_items) || share.policy !== 'property_units_occupied_days'
    || !share.vacant_unit_days || typeof share.vacant_unit_days !== 'object' || Array.isArray(share.vacant_unit_days)) throw invalid();
  const totals = Object.fromEntries(moneyKeys.map(key => [key, cents(share[key])]));
  if (totals.total_amount !== totals.recoverable_vacancy_amount + totals.non_recoverable_amount
    || totals.property_cost_total !== totals.tenant_cost_total + totals.total_amount) throw invalid();
  for (const [unitId, days] of Object.entries(share.vacant_unit_days)) {
    if (!id(unitId) || !Number.isSafeInteger(days) || days < 0) throw invalid();
  }
  let vacancy = 0, nonRecoverable = 0;
  const lineItems = share.line_items.map((line, index) => {
    if (!line || !id(line.cost_item_id) || typeof line.description !== 'string'
      || !['vacancy', 'non_recoverable'].includes(line.reason)) throw invalid();
    if (line.reason === 'vacancy' ? !id(line.unit_id) : line.unit_id != null) throw invalid();
    const amount = cents(line.allocated_amount);
    if (line.reason === 'vacancy') vacancy += amount;
    else nonRecoverable += amount;
    return { ...line, id: `${line.cost_item_id}:${line.unit_id || 'property'}:${index}`, allocated_amount: amount / 100 };
  });
  if (!Number.isSafeInteger(vacancy) || !Number.isSafeInteger(nonRecoverable)
    || vacancy !== totals.recoverable_vacancy_amount || nonRecoverable !== totals.non_recoverable_amount) throw invalid();
  return { ...share, ...Object.fromEntries(moneyKeys.map(key => [key, totals[key] / 100])), line_items: lineItems };
}
