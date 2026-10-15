import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import DataTable from '../components/DataTable';
import { entityHref } from '../utils/entityLinks';

const party = vi.hoisted(() => ({ openParty: vi.fn() }));
vi.mock('../features/partyWorkspace/PartyWorkspace', () => ({
  PartyLink: ({ tenantId, children }) => <button type="button" onClick={e => { e.stopPropagation(); party.openParty(tenantId); }}>{children}</button>,
}));

function Where() { const l = useLocation(); return <span data-testid="where">{l.pathname + l.search}</span>; }

const rows = [
  { id: 'c1', unit_label: 'EG links', property_name: 'Kastanienallee 42', unit_id: 'u1', property_id: 'p1',
    tenant_name: 'Anna Schmidt', tenant_id: 't1', supplier: 'Wärmemeister GmbH' },
  { id: 'c2', unit_label: '—', property_name: '—', unit_id: null, property_id: null, tenant_name: '—', tenant_id: null, supplier: '' },
];
const columns = [
  { key: 'unit_label', subKey: 'property_name', label: 'Einheit', link: 'unit', subLink: 'property' },
  { key: 'tenant_name', label: 'Mieter', link: 'tenant' },
  { key: 'supplier', label: 'Lieferant', link: 'contact' },
];

beforeEach(() => { localStorage.clear(); party.openParty.mockReset(); });
afterEach(() => cleanup());

describe('links between records', () => {
  it('builds the target of every kind', () => {
    expect(entityHref('property', 'p 1')).toBe('/properties/p%201');
    expect(entityHref('unit', 'u1')).toBe('/units/u1');
    expect(entityHref('invoiceReview', 'i1')).toBe('/invoice-review/i1');
    expect(entityHref('contact', null, 'Müller & Co')).toBe('/contacts?suche=M%C3%BCller%20%26%20Co');
    expect(entityHref('contract', null, 'MV-2025-001')).toBe('/contracts?suche=MV-2025-001');
    expect(entityHref('property', null)).toBeNull();
  });

  it('turns names into links, also the second line, and leaves empty cells as they are', () => {
    const onRowClick = vi.fn();
    render(<MemoryRouter initialEntries={['/contracts']}>
      <Routes><Route path="*" element={<><Where /><DataTable title="Verträge" columns={columns} data={rows} onRowClick={onRowClick} /></>} /></Routes>
    </MemoryRouter>);
    const first = screen.getAllByRole('row')[1];
    expect(within(first).getByRole('link', { name: 'EG links' })).toHaveAttribute('href', '/units/u1');
    expect(within(first).getByRole('link', { name: 'Kastanienallee 42' })).toHaveAttribute('href', '/properties/p1');
    expect(within(first).getByRole('link', { name: 'Wärmemeister GmbH' })).toHaveAttribute('href', '/contacts?suche=W%C3%A4rmemeister%20GmbH');
    expect(within(screen.getAllByRole('row')[2]).queryByRole('link')).toBeNull();

    // a click on a name opens the name, not the row
    fireEvent.click(within(first).getByRole('link', { name: 'EG links' }));
    expect(onRowClick).not.toHaveBeenCalled();
    expect(screen.getByTestId('where')).toHaveTextContent('/units/u1');
  });

  it('opens the party file of a tenant without opening the row', () => {
    const onRowClick = vi.fn();
    render(<MemoryRouter><DataTable title="Buchungen" columns={columns} data={rows} onRowClick={onRowClick} /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'Anna Schmidt' }));
    expect(party.openParty).toHaveBeenCalledWith('t1');
    expect(onRowClick).not.toHaveBeenCalled();
  });

  it('starts a list with the search a link carries, on page 1 and without stale filters', () => {
    sessionStorage.setItem('table_view:/contacts|Kontakte', JSON.stringify({ search: 'alt', page: 3, columnFilters: { supplier: 'x' } }));
    window.history.pushState({}, '', '/contacts?suche=W%C3%A4rmemeister');
    const contacts = [{ id: 'k1', supplier: 'Wärmemeister GmbH' }, { id: 'k2', supplier: 'Dachdeckerei Hoch' }];
    render(<DataTable title="Kontakte" columns={[{ key: 'supplier', label: 'Name', filterType: 'text' }]} data={contacts} />);
    expect(screen.getByRole('textbox', { name: 'Kontakte durchsuchen' })).toHaveValue('Wärmemeister');
    expect(screen.getAllByRole('row')).toHaveLength(2);
    window.history.pushState({}, '', '/');
  });
});
