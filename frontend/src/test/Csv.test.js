import { describe, expect, it } from 'vitest';
import { csvCell } from '../utils/csv';

describe('literal spreadsheet CSV fields', () => {
  it.each(['=1+1', '+SUM(1)', '-CMD()', '@SUM(1)', '  =1+1', '\tName', '\rName', '\n=1+1', '\u00a0+SUM(1)',
    '\ufeff=1+1', '\x00=1+1', '\x01 \t@SUM(1)'])(
    'protects text %j including whitespace prefixes', text => {
      const encoded = csvCell(text);
      expect(encoded.startsWith("'") || encoded.startsWith('"\'')).toBe(true);
    });

  it('retains numeric negatives, Unicode, nulls and an existing literal prefix', () => {
    expect(csvCell(-123.45)).toBe('-123.45');
    expect(csvCell(null)).toBe('');
    expect(csvCell('Öztürk')).toBe('Öztürk');
    expect(csvCell("'=1+1")).toBe("'=1+1");
  });

  it('quotes commas, quotes, CR-only and multiline content', () => {
    expect(csvCell('Mieter, Partei')).toBe('"Mieter, Partei"');
    expect(csvCell('Name "A"')).toBe('"Name ""A"""');
    expect(csvCell('A\rB')).toBe('"A\rB"');
    expect(csvCell('A\nB')).toBe('"A\nB"');
    expect(csvCell('=HYPERLINK("example.invalid","X")')).toBe('"\'=HYPERLINK(""example.invalid"",""X"")"');
  });
});
