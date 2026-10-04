export const originalHash = 'a'.repeat(64);
export const snapshotHash = 'b'.repeat(64);
export const originalStatement = { id: 'statement-original', billing_period_id: 'period', contract_id: 'contract', unit_id: 'unit',
  revision: 3, status: 'finalized', snapshot_hash: snapshotHash, total_cost: 123.45, advance_paid: 100, balance: 23.45,
  line_items: Array.from({ length: 28 }, (_, index) => ({ description: `Original position ${index + 1}`, allocated_amount: index + 0.25 })) };
export const evidence = { document_id: 'document', version_id: 'version', filename: 'Original.txt', media_type: 'text/plain', size_bytes: 3, sha256: 'c'.repeat(64) };
export const event = (revision = 1) => ({ id: `event-${revision}`, case_id: 'case', command_id: `command-${revision}`, revision,
  kind: revision === 1 ? 'opened' : 'note', reason: `Original reason ${revision}`, actor_id: 'actor-original',
  observed_on: '2026-10-01', created_at: '2026-10-03T12:00:00Z', line_item_refs: revision === 1 ? [0, 27] : [], evidence: [evidence],
  corrects_event_id: null, correction_statement_id: null });
export const caseRow = { id: 'case', period_id: 'period', property_id: 'property', statement_id: originalStatement.id,
  tenant_id: 'retained-tenant', contract_id: 'contract', unit_id: 'unit', case_kind: 'tenant_statement', state: 'in_review', revision: 27,
  statement_revision: 3, original_snapshot: originalStatement, original_hash: originalHash, snapshot_hash: snapshotHash, latest_event: event(27),
  created_at: '2026-10-03T12:00:00Z', party_binding: 'verified_at_case_opening',
  party_binding_note: 'Historical tenant identity is not contained in this statement; verified when this file was opened.' };
export const periodStatus = { period_id: 'period', legacy_disputed_without_complete_case: false, case_count: 27, open_case_count: 1,
  property_review_original: null, property_review_snapshot_hash: null, financial_effect: 'none' };
export const casePage = { items: [caseRow], next_after_id: null };
export const preview = command => ({ request: command, preview_hash: 'd'.repeat(64), binding: { ...caseRow,
  statement_revision: command.expected_statement_revision ?? null, statement_id: command.statement_id ?? null }, evidence: [], state: null, previous_hash: null, correction: null });
