import { expect, it } from 'vitest';
import { readingToForm } from '../features/aiReading/aiReadingApi';

it('übernimmt konkrete Fundstellen und ihren Prüfstatus unverändert in die Maske', () => {
  const citation = { version_id: 'v-7', line: 4, start_char: 10, end_char: 22, verified: true, quote: 'Betrag 10.00' };
  const result = readingToForm({ reader: 'claude', values: {
    gross_amount: { value: '10.00', evidence: citation.quote, confidence: 'high', citation, evidence_status: 'verified' },
    supplier: { value: 'Unbelegt', evidence_status: 'missing', confidence: 'low', citation: null },
  } }, { gross: 'gross_amount', supplier: 'supplier' });
  expect(result.marks.gross.citation).toEqual(citation);
  expect(result.marks.gross.evidence_status).toBe('verified');
  expect(result.marks.supplier.citation).toBeNull();
  expect(result.marks.supplier.evidence_status).toBe('missing');
});

