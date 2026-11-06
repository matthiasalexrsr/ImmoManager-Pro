import { describe, expect, it } from 'vitest';
import { originalRetryReview, workingAttachmentIds } from '../features/assistant/assistantRetry';

const original = extra => ({ data_scope: 'selected', context: { property_ids: ['p1'], unit_ids: [], tenant_ids: [] },
  effective_attachment_ids: ['file1'], web_research: false, report: null, ...extra });
const current = extra => ({ scope: 'selected', context: [{ kind: 'property', id: 'p1' }], attachmentIds: ['file1'], webResearch: false, report: null, ...extra });

describe('Freigabe einer Originalanfrage zur Wiederholung', () => {
  it('vergleicht die eigentliche Auswahl und nicht zusätzlich gelesene Belegquellen', () => {
    const result = originalRetryReview(original({ sources: [{ kind: 'property', id: 'p1' }, { kind: 'unit', id: 'related-only' }] }), current());
    expect(result).toMatchObject({ allowed: true, selectedCount: 1, fileCount: 1, webResearch: false });
  });

  it.each([
    { scope: 'none' }, { scope: 'authorized' },
    { context: [{ kind: 'property', id: 'p2' }] }, { context: [] },
    { attachmentIds: [] }, { attachmentIds: ['file1', 'file2'] },
    { webResearch: true },
    { report: { version: 2, kind: 'cash-v2', as_of: '2026-11-06', property_id: 'p1' } },
  ])('verhindert eine Wiederholung bei geändertem aktuellem Umfang %j', change => {
    expect(originalRetryReview(original(), current(change))).toMatchObject({ allowed: false, complete: true });
  });

  it.each(['data_scope', 'context', 'effective_attachment_ids', 'web_research', 'report'])('verweigert bei fehlender Originalangabe %s', key => {
    const run = original(); delete run[key];
    expect(originalRetryReview(run, current())).toMatchObject({ allowed: false, complete: false });
  });

  it('behandelt leere Felder, Reihenfolge und doppelte IDs nach dem serverseitigen Auswahlvertrag', () => {
    expect(originalRetryReview(original({ context: { unit_ids: [], property_ids: ['p2', 'p1', 'p1'] }, effective_attachment_ids: ['file2', 'file1'] }),
      current({ context: [{ kind: 'property', id: 'p1' }, { kind: 'property', id: 'p2' }], attachmentIds: ['file1', 'file2', 'file1'] })).allowed).toBe(true);
  });

  it('verlangt für inzwischen geänderte Quellen eine neue Anfrage zum aktuellen Stand', () => {
    expect(originalRetryReview(original({ verification_status: 'stale' }), current())).toMatchObject({ allowed: false, complete: true });
  });

  it('ignoriert bei none inaktive Akten und Berichte, erhält aber die tatsächliche Dateiauswahl', () => {
    const run = original({ data_scope: 'none', context: {} });
    expect(originalRetryReview(run, current({ scope: 'none', report: { kind: 'cash-v2' } })).allowed).toBe(true);
    expect(originalRetryReview(run, current({ scope: 'none', attachmentIds: [] })).allowed).toBe(false);
  });

  it('erkennt denselben Bericht einschließlich der veröffentlichten Serverdefaults und unterscheidet echte Änderungen', () => {
    const definition = { version: 2, kind: 'liquidity-v2', as_of: '2026-11-06', property_id: 'p1' };
    const publicDefinition = { ...definition, unit_id: null, portfolio_id: null, months: 12, date_from: null, date_to: null,
      rent_payment_day: 3, rent_collection_percent: '100.00', arrears_collection_percent: '0.00', vacant_unit_ids: [], planned_flows: [] };
    expect(originalRetryReview(original({ report: publicDefinition }), current({ report: definition })).allowed).toBe(true);
    expect(originalRetryReview(original({ report: publicDefinition }), current({ report: { ...definition, as_of: '2026-11-07' } })).allowed).toBe(false);
  });

  it('zieht eine abgewählte Arbeitsdatei auch dann ab, wenn sie zum ursprünglichen Chat gehörte', () => {
    expect(workingAttachmentIds({ attachment_ids: ['old1', 'old2'] }, original(), { attachments: [{ id: 'new1' }], excluded_attachment_ids: ['old1'] }))
      .toEqual(['old2', 'new1']);
  });
});
