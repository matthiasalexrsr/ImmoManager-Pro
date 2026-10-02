export function emptySummary(periodId = 'period') {
  return { period_id: periodId, settlements: [], credits_total: 0, debts_total: 0, net_amount: 0 };
}

export function mixedSummary(periodId = 'period') {
  const row = (id, amount, kind, status, receivableId = null) => ({
    id, billing_period_id: periodId, statement_id: `statement-${id}`,
    root_statement_id: `root-${id}`, source_statement_id: `source-${id}`,
    contract_id: `contract-${id}`, signed_amount: amount, kind, status,
    receivable_id: receivableId, created_at: '2026-01-01T00:00:00Z',
  });
  return { period_id: periodId, settlements: [
    row('debt', '360.00', 'debt', 'receivable_created', 'receivable-debt'),
    row('credit', '-75.00', 'credit', 'credit_available'),
    row('none', '0.00', 'none', 'no_adjustment'),
  ], credits_total: '75.00', debts_total: '360.00', net_amount: '285.00' };
}

export function postedSummary(periodId = 'period') {
  return { ...mixedSummary(periodId), created_receivables: 1, created_credits: 1,
    created_settlements: 3, existing_count: 0 };
}
