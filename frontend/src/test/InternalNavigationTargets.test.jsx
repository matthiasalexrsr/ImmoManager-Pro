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
  it('filters malformed routes and avoids duplicate related-page links', () => {
    render(<MemoryRouter><RelatedPageLinks items={[{ to: '/documents?focus_id=d1', label: 'Original' }, { to: '/documents?focus_id=d1', label: 'Original' }, { to: '/\\foreign.test', label: 'Ungültig' }, null]} /></MemoryRouter>);
    expect(screen.getAllByRole('link')).toHaveLength(1);
    expect(screen.getByRole('link', { name: 'Original' })).toHaveAttribute('href', '/documents?focus_id=d1');
  });
});
