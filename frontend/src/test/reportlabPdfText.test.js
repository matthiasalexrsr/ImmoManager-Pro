import { describe, expect, it } from 'vitest';
import { deflateSync } from 'node:zlib';
import { decodeAscii85, extractReportlabText } from '../../e2e/reportlabPdfText.mjs';

function pdf(stream, filter = '') {
  return Buffer.concat([Buffer.from(`%PDF-1.4\n1 0 obj\n<< /Length ${stream.length} ${filter} >>\nstream\n`),
    stream, Buffer.from('\nendstream\nendobj\n%%EOF\n')]);
}

describe('ReportLab PDF text test helper', () => {
  // Reference vectors produced by Python's stdlib base64.a85encode(adobe=True).
  it.each([['5l', 'A'], ['5sb', 'AB'], ['5sdp', 'ABC'], ['5sdq,', 'ABCD'],
    ['87cURD]j7BEbo80', 'Hello world!'], ['z', '\0\0\0\0']])('decodes ASCII85 %s', (encoded, expected) => {
    expect(decodeAscii85(Buffer.from(`<~${encoded}~>`)).toString()).toBe(expected);
  });
  it('extracts literal text from a FlateDecode content stream', () => {
    const bytes = pdf(deflateSync(Buffer.from('BT (Revision: 3) Tj (Unit \\(A\\)) Tj ET')), '/Filter /FlateDecode');
    expect(extractReportlabText(bytes)).toBe('Revision: 3\nUnit (A)');
  });
  it('decodes ReportLab ASCII85+Flate filters in declared order', () => {
    const stream = Buffer.from('<~Garg^;:#S@/^#]jbg3Un0[`o+a\\pK)c-4@%bq-+tE!5c<6NH!s$Ru~>');
    const text = extractReportlabText(pdf(stream, '/Filter [ /ASCII85Decode /FlateDecode ]'));
    expect(text).toBe('Revision: 2\nEinheit: A');
    expect([...text.matchAll(/\bRevision:\s*(\d+)\b/g)].map(match => Number(match[1]))).toEqual([2]);
  });
  it('does not mistake document metadata for displayed revision text', () => {
    const bytes = Buffer.concat([Buffer.from('%PDF-1.4\n% Revision: 2\n'),
      pdf(Buffer.from('BT (Revision: 1) Tj ET'))]);
    expect(extractReportlabText(bytes)).toBe('Revision: 1');
  });
  it.each(['!', '!z', '~~~~~', 'uuuuu'])('rejects malformed ASCII85 %s', value => {
    expect(() => decodeAscii85(Buffer.from(value))).toThrow();
  });
  it('rejects unsupported streams or non-PDF responses', () => {
    expect(() => extractReportlabText(Buffer.from('Revision: 2'))).toThrow();
    expect(() => extractReportlabText(pdf(Buffer.from('anything'), '/Filter /LZWDecode'))).toThrow();
    expect(() => extractReportlabText(pdf(Buffer.from('no text operators')))).toThrow();
  });
});
