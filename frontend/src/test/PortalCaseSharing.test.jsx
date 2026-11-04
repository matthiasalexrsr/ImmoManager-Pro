import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import PortalConversations from '../features/externalPortal/PortalConversations';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), captureSession: vi.fn(() => () => {}) } }));
const record = { id: 'case-1', property_id: 'property-1', unit_id: 'unit-1', updated_at: '2026-11-04T12:00:00Z' };
const grant = { id: 'grant-101', active: true, identity_active: true, revision: 7, email: 'partei@example.test',
  binding: { property_id: 'property-1', unit_id: 'unit-1' } };
const page = (items, total=items.length) => ({ items, total, skip: 0, limit: 100 });
beforeEach(() => {
  vi.resetAllMocks();
  api.get.mockImplementation(async path => path.startsWith('/portal-admin/grants?') ? page([grant]) : page([]));
  api.post.mockResolvedValue({ id: 'published-case' });
});
afterEach(cleanup);

describe('manual portal publication of an existing internal case', () => {
  it('continues the paged response and publishes only the explicitly selected matching active party', async () => {
    const earlier = Array.from({ length: 100 }, (_, index) => ({ ...grant, id: `inactive-${index}`, active: false }));
    earlier[0] = { ...grant, id: 'foreign-unit', email: 'fremd@example.test', binding: { ...grant.binding, unit_id: 'other-unit' } };
    api.get.mockImplementation(async path => {
      if (!path.startsWith('/portal-admin/grants?')) return page([]);
      const params = new URL(path, 'http://audit.test').searchParams;
      expect(params.get('case_id')).toBe(record.id); expect(params.get('limit')).toBe('100');
      return page(params.get('skip') === '0' ? earlier : [grant], 101);
    });
    render(<MemoryRouter><PortalConversations caseId={record.id} caseRecord={record} /></MemoryRouter>);
    fireEvent.click(screen.getByText('Diese Schadenakte ausdrücklich einer Portalpartei zuordnen'));
    const select = screen.getByLabelText('Aktive Partei für diese Einheit');
    await waitFor(() => expect(select).toBeEnabled());
    expect(screen.getByRole('option', { name: grant.email })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'fremd@example.test' })).not.toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
    fireEvent.change(select, { target: { value: grant.id } });
    fireEvent.change(screen.getByLabelText('Für die Partei sichtbarer Titel'), { target: { value: 'Fenster wird geprüft' } });
    fireEvent.change(screen.getByLabelText('Begründung und geprüfte Zugehörigkeit'), { target: { value: 'Identität und Verhältnis persönlich geprüft.' } });
    fireEvent.submit(select.closest('form'));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/portal-admin/grants/grant-101/cases', expect.objectContaining({
      grant_revision: 7, case_id: record.id, case_updated_at: record.updated_at, title: 'Fenster wird geprüft',
    })));
    expect(api.get.mock.calls.some(([path]) => path.includes('skip=100'))).toBe(true);
  });

  it('shows a failed grant lookup and reloads it without enabling an incomplete selection', async () => {
    let rejected = false;
    api.get.mockImplementation(async path => {
      if (!path.startsWith('/portal-admin/grants?')) return page([]);
      if (!rejected) { rejected = true; throw new Error('Zuordnungen vorübergehend nicht erreichbar'); }
      return page([grant]);
    });
    render(<MemoryRouter><PortalConversations caseId={record.id} caseRecord={record} /></MemoryRouter>);
    fireEvent.click(screen.getByText('Diese Schadenakte ausdrücklich einer Portalpartei zuordnen'));
    expect(await screen.findByRole('alert')).toHaveTextContent('nicht erreichbar');
    expect(screen.getByLabelText('Aktive Partei für diese Einheit')).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Zuordnungen neu laden' }));
    await waitFor(() => expect(screen.getByLabelText('Aktive Partei für diese Einheit')).toBeEnabled());
    expect(api.post).not.toHaveBeenCalled();
  });
});
