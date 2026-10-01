import { describe, expect, it } from 'vitest';
import { parseSettlementPosting, parseSettlementSummary } from '../utils/billingSettlements';
import { emptySummary, mixedSummary, postedSummary } from './fixtures/settlements';

describe('billing settlement response contract', () => {
  it('preserves separate debt, credit and signed net totals without inventing payouts', () => {
    const parsed = parseSettlementSummary(mixedSummary(), 'period');
    expect([parsed.debts_total, parsed.credits_total, parsed.net_amount]).toEqual([360, 75, 285]);
    expect(parsed.settlements.map(row => row.signed_amount)).toEqual([360, -75, 0]);
    expect(parsed.settlements[1].status).toBe('credit_available');
    expect(parsed.settlements[1].receivable_id).toBeNull();
  });
  it('accepts a genuinely empty ledger', () => {
    expect(parseSettlementSummary(emptySummary(), 'period')).toEqual(emptySummary());
  });
  it.each([undefined, null, true, '', ' ', 'NaN', 'Infinity', '1.001', 0.001])('rejects invalid money %j', value => {
    expect(() => parseSettlementSummary({ ...mixedSummary(), credits_total: value }, 'period')).toThrow();
  });
  it.each([
    body => { body.period_id = 'other'; },
    body => { body.settlements = null; },
    body => { body.net_amount = 0; },
    body => { body.credits_total = -75; },
    body => { body.settlements[0].billing_period_id = 'other'; },
    body => { body.settlements[1].status = 'paid'; },
    body => { body.settlements[1].kind = 'debt'; },
    body => { body.settlements[2].receivable_id = 'unexpected-claim'; },
    body => { body.settlements[0].receivable_id = null; },
    body => { body.settlements[1].id = body.settlements[0].id; },
    body => { body.settlements[1].statement_id = body.settlements[0].statement_id; },
    body => { body.settlements[0].signed_amount = 100; },
  ])('rejects inconsistent or incomplete ledgers (%#)', mutate => {
    const body = mixedSummary();
    mutate(body);
    expect(() => parseSettlementSummary(body, 'period')).toThrow('Invalid billing settlement response');
  });
  it('accepts repeat postings with only existing entries', () => {
    const body = { ...postedSummary(), created_receivables: 0, created_credits: 0,
      created_settlements: 0, existing_count: 3 };
    expect(parseSettlementPosting(body, 'period').existing_count).toBe(3);
  });
  it.each(['created_receivables', 'created_credits', 'created_settlements', 'existing_count'])('requires a valid %s count', key => {
    expect(() => parseSettlementPosting({ ...postedSummary(), [key]: undefined }, 'period')).toThrow();
    expect(() => parseSettlementPosting({ ...postedSummary(), [key]: -1 }, 'period')).toThrow();
  });
});

describe('legacy credit references', () => {
  it('retains a historical negative-receivable reference without converting the credit to debt', () => {
    const body = mixedSummary();
    body.settlements[1].receivable_id = 'legacy-credit-evidence';
    const parsed = parseSettlementSummary(body, 'period');
    expect(parsed.settlements[1]).toMatchObject({ signed_amount: -75, kind: 'credit',
      status: 'credit_available', receivable_id: 'legacy-credit-evidence' });
    expect(parsed.credits_total).toBe(75);
    expect(parsed.debts_total).toBe(360);
  });
  it.each(['', ' ', 42, false, {}, []])('rejects invalid historical reference %j', reference => {
    const body = mixedSummary();
    body.settlements[1].receivable_id = reference;
    expect(() => parseSettlementSummary(body, 'period')).toThrow();
  });
});
