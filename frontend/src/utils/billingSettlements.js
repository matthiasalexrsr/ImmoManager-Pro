const statuses = { debt: 'receivable_created', credit: 'credit_available', none: 'no_adjustment' };
const invalid = () => Object.assign(new Error('Invalid billing settlement response'), { code: 'INVALID_SETTLEMENT_RESPONSE' });
const identifier = value => typeof value === 'string' && value.trim().length > 0;

function cents(value) {
  if (!['string', 'number'].includes(typeof value) || String(value).trim() === '') throw invalid();
  const amount = Number(value) * 100;
  const rounded = Math.round(amount);
  if (!Number.isSafeInteger(rounded) || Math.abs(amount - rounded) > 0.000001) throw invalid();
  return rounded;
}

/** Only render a complete, internally consistent period ledger, never zero-fill errors. */
export function parseSettlementSummary(body, periodId) {
  if (body?.period_id !== periodId || !Array.isArray(body.settlements)) throw invalid();
  const debts = cents(body.debts_total), credits = cents(body.credits_total), net = cents(body.net_amount);
  if (debts < 0 || credits < 0 || net !== debts - credits) throw invalid();
  const ids = new Set(), statementIds = new Set();
  let calculatedDebts = 0, calculatedCredits = 0;
  const settlements = body.settlements.map(row => {
    if (!row || !identifier(row.id) || !identifier(row.statement_id) || !identifier(row.contract_id)
      || row.billing_period_id !== periodId || ids.has(row.id) || statementIds.has(row.statement_id)) throw invalid();
    const amount = cents(row.signed_amount);
    const kind = amount > 0 ? 'debt' : amount < 0 ? 'credit' : 'none';
    if (row.kind !== kind || row.status !== statuses[kind]) throw invalid();
    if ((kind === 'debt' && !identifier(row.receivable_id))
      || (kind === 'none' && row.receivable_id != null)
      || (kind === 'credit' && row.receivable_id != null && !identifier(row.receivable_id))) throw invalid();
    ids.add(row.id); statementIds.add(row.statement_id);
    calculatedDebts += Math.max(0, amount);
    calculatedCredits += Math.max(0, -amount);
    return { ...row, signed_amount: amount / 100 };
  });
  if (!Number.isSafeInteger(calculatedDebts) || !Number.isSafeInteger(calculatedCredits)
    || calculatedDebts !== debts || calculatedCredits !== credits) throw invalid();
  return { ...body, settlements, debts_total: debts / 100, credits_total: credits / 100, net_amount: net / 100 };
}

export function parseSettlementPosting(body, periodId) {
  const result = parseSettlementSummary(body, periodId);
  for (const key of ['created_receivables', 'created_credits', 'created_settlements', 'existing_count']) {
    if (!Number.isSafeInteger(result[key]) || result[key] < 0) throw invalid();
  }
  return result;
}
