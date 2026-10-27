import { describe, expect, it } from 'vitest';
import { buildCsv, csvCell } from '../utils/tableCsv';

describe('spreadsheet exports after workflow integration', () => {
  it.each(['  =1+1', '\ufeff@SUM(1)', '\x00+SUM(1)', '\nName'])(
    'keeps suspicious string %j literal in cells and headings', text => {
      expect(csvCell({}, text)).toMatch(/^"?'/);
      expect(buildCsv([{ key: 'name', label: text }], [])).toMatch(/^"?'/);
    });
  it('retains decimal commas, numeric negative strings and separator quoting', () => {
    expect(buildCsv([{ key: 'amount', label: 'Betrag; EUR', type: 'currency' }], [
      { amount: '-12.50' }, { amount: -1.5 }, { amount: '=1+1' },
    ])).toBe('"Betrag; EUR"\r\n-12,50\r\n-1,5\r\n\'=1+1');
  });
});
