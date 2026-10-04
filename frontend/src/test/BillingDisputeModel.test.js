import { describe, expect, it } from 'vitest';
import { appendCommand, canonical, copy, openCommand, permittedEvents, readCase, readCasePage, readJournal, readPreview, readReceipt, readStatement, readStatus, restoreEnvelope } from '../features/billingDisputes/disputeModel';
import { casePage, caseRow, event, originalStatement, periodStatus, preview } from './fixtures/disputes';

describe('dispute original and exact command contracts', () => {
  it('rejects a different case, period or original revision rather than displaying it', () => {
    expect(readCase(caseRow, 'case', 'period')).toBe(caseRow);
    for (const [id, period] of [['foreign', 'period'], ['case', 'foreign']]) expect(() => readCase(caseRow, id, period)).toThrow('invalidDisputeResponse');
    expect(() => readCase({ ...caseRow, statement_revision: 4 }, 'case', 'period')).toThrow();
    expect(readStatement(originalStatement, originalStatement.id, 'period')).toBe(originalStatement);
    expect(() => readStatement({ ...originalStatement, status: 'draft' }, originalStatement.id, 'period')).toThrow();
  });
  it('validates whole-count status without turning missing or malformed replies into zero', () => {
    expect(readStatus(periodStatus, 'period').case_count).toBe(27);
    for (const value of [[], null, { ...periodStatus, open_case_count: 28 }]) expect(() => readStatus(value, 'period')).toThrow();
  });
  it('keeps bounded case packets complete and rejects duplicate, foreign and oversized pages', () => {
    expect(readCasePage(casePage, 'period').items).toHaveLength(1);
    for (const value of [{ ...casePage, items: [caseRow, caseRow] }, { ...casePage, next_after_id: 'wrong' },
      { ...casePage, items: Array.from({ length: 26 }, (_, i) => ({ ...caseRow, id: String(i) })) }]) expect(() => readCasePage(value, 'period')).toThrow();
    expect(() => readCasePage(casePage, 'foreign')).toThrow();
  });
  it('validates revision keysets and never accepts a repeated or backwards event', () => {
    const page = { items: [event(1), event(2)], next_after: 2, revision: 27 };
    expect(readJournal(page, 'case').next_after).toBe(2);
    expect(() => readJournal(page, 'case', 1)).toThrow();
    expect(() => readJournal({ ...page, items: [event(2), event(1)] }, 'case')).toThrow();
    expect(() => readJournal({ ...page, next_after: 3 }, 'case')).toThrow();
  });
  it('binds a preview to the unchanged complete JSON request and original source', () => {
    const command = { ...openCommand('period', originalStatement, 'tenant_statement', 'same-key'), reason: 'Exact reason', received_on: '2026-10-01' };
    const result = preview(command);
    expect(readPreview(result, command).command).toEqual({ ...command, preview_hash: result.preview_hash });
    expect(() => readPreview({ ...result, request: { ...command, reason: 'Changed' } }, command)).toThrow();
    expect(() => readPreview({ ...result, binding: { ...result.binding, snapshot_hash: 'f'.repeat(64) } }, command)).toThrow();
    expect(() => readPreview({ ...result, evidence: [{ version_id: 'missing' }] }, command)).toThrow();
  });
  it('restores the same pending command and preview hash without a replacement identifier or revision', () => {
    const command = { ...openCommand('period', originalStatement, 'tenant_statement', 'retained-key'), reason: 'Saved input', received_on: '2026-10-01' };
    const checked = readPreview(preview(command), command);
    const values = { period_id: 'period', case_id: '', command_json: JSON.stringify(checked.command), review_json: JSON.stringify(checked.review) };
    const restored = restoreEnvelope(values, 'period');
    expect(canonical(restored.command)).toBe(canonical(checked.command));
    expect(restored.command.idempotency_key).toBe('retained-key');
    expect(() => restoreEnvelope(values, 'foreign')).toThrow();
    expect(() => restoreEnvelope(values, 'period', 'different-case')).toThrow();
  });
  it('uses actual journal states and preserves the original expected revision', () => {
    expect(permittedEvents('closed', 'tenant_statement')).toContain('reopened');
    expect(permittedEvents('closed', 'property_review')).not.toContain('correction_link');
    expect(permittedEvents('open', 'tenant_statement')).not.toContain('reopened');
    const command = appendCommand(caseRow, 'note', 'kept');
    expect(command.expected_revision).toBe(27);
    expect(() => appendCommand(caseRow, 'reopened')).toThrow();
  });
  it('requires an exact confirmation receipt and makes no implied financial change', () => {
    const command = appendCommand(caseRow, 'note', 'kept');
    expect(readReceipt({ case_id: 'case', revision: 28, event_id: 'event-28' }, command, 'case').revision).toBe(28);
    expect(() => readReceipt({ case_id: 'case', revision: 29, event_id: 'event-29' }, command, 'case')).toThrow();
    expect(() => readReceipt({ case_id: 'wrong', revision: 28, event_id: 'event-28' }, command, 'case')).toThrow();
    expect(copy(originalStatement)).toEqual(originalStatement);
  });
});
