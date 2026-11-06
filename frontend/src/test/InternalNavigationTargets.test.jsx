import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import RelatedPageLinks from '../components/RelatedPageLinks';
import { safeInternalHref } from '../utils/internalLinks';
import { contextHref, safeLocalHref } from '../features/assistant/assistantLinks';

afterEach(cleanup);
describe('internal navigation targets', () => {
  it.each(['//foreign.test', '/\\foreign.test', '/ok\nroute', '/ok\x7froute', 'javascript:alert(1)', 'https://foreign.test', null])('rejects browser URL syntax outside app paths: %s', value => {
    expect(safeInternalHref(value)).toBe(''); expect(safeLocalHref(value)).toBe('');
  });
  it('keeps exact source IDs linked even for older messages without href metadata', () => {
    expect(contextHref({ kind: 'contract', id: 'c/1' })).toBe('/contracts?contract_id=c%2F1');
    expect(contextHref({ kind: 'booking', id: 'b 1' })).toBe('/bookings?booking_id=b%201');
    expect(contextHref({ kind: 'task', id: 't/1' })).toBe('/tasks?focus_id=t%2F1');
    expect(contextHref({ kind: 'invoice', id: 'i1' })).toBe('/invoices?focus_id=i1');
    expect(contextHref({ kind: 'service_contract', id: 's1' })).toBe('/service-contracts/s1');
    expect(contextHref({ kind: 'unknown', id: 'u1' })).toBe('');
    expect(contextHref({ kind: 'task' })).toBe('');
  });
  it('keeps source identity authoritative over stale or mismatched supplied URLs', () => {
    expect(contextHref({ kind: 'task', id: 't1', href: '/tasks?focus_id=t2' })).toBe('/tasks?focus_id=t1');
    expect(contextHref({ kind: 'task', id: 't1', href: '/tasks/t1' })).toBe('/tasks?focus_id=t1');
    expect(contextHref({ kind: 'contract', id: 'c1', href: '/contracts?contract_id=c1&focus_id=c2' })).toBe('/contracts?contract_id=c1');
    expect(contextHref({ kind: 'task', id: 't1', href: '/properties/p2' })).toBe('/tasks?focus_id=t1');
    expect(contextHref({ kind: 'contract', id: 'c1', href: '/contracts?contract_id=c2&focus_id=c1' })).toBe('/contracts?contract_id=c1');
    expect(contextHref({ kind: 'contract', id: 'c1', href: '/contracts?focus_id=c1&notice_id=n1' })).toBe('/contracts?focus_id=c1&notice_id=n1');
    expect(contextHref({ kind: 'invoice', id: 'i1', href: '/invoice-review/i1' })).toBe('/invoice-review/i1');
    expect(contextHref({ kind: 'document', id: 'd1', href: '/documents/d2' })).toBe('/documents/d1');
    expect(contextHref({ kind: 'note', id: 'n1', href: '/properties/p1?tab=notes' })).toBe('/properties/p1?tab=notes');
  });
  it.each([
    ['meter', '/meters?focus_id=id1'], ['calendar', '/calendar?focus_id=id1'],
    ['portfolio', '/portfolios?focus_id=id1'], ['utility_statement', '/statements?statement_id=id1'],
    ['billing_period', '/statements?period_id=id1'],
  ])('checks the identity of assistant source kind %s', (kind, href) => {
    expect(contextHref({ kind, id: 'id1', href: '/tasks?focus_id=unrelated' })).toBe(href);
  });
  it('keeps child readings bound to their actual meter and exact source ID', () => {
    const card = { kind: 'standalone_reading', id: 'r1', values: { meter_id: 'm1' } };
    const expected = '/meters?focus_id=m1&source_id=r1';
    expect(contextHref({ ...card, href: expected })).toBe(expected);
    expect(contextHref({ ...card, href: '/meters?focus_id=m2&source_id=r1' })).toBe(expected);
    expect(contextHref({ ...card, href: '/tasks?focus_id=r1' })).toBe(expected);
  });
  it('filters malformed routes and avoids duplicate related-page links', () => {
    render(<MemoryRouter><RelatedPageLinks items={[{ to: '/documents?focus_id=d1', label: 'Original' }, { to: '/documents?focus_id=d1', label: 'Original' }, { to: '/\\foreign.test', label: 'Ungültig' }, null]} /></MemoryRouter>);
    expect(screen.getAllByRole('link')).toHaveLength(1);
    expect(screen.getByRole('link', { name: 'Original' })).toHaveAttribute('href', '/documents?focus_id=d1');
  });
});
