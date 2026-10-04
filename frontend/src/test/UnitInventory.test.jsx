import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import german from '../../../i18n/de-DE.json';
import Units from '../pages/Units';

const mocks = vi.hoisted(() => ({ get: vi.fn(), getBlob: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), user: null }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: mocks.user }) }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => null }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => vi.fn().mockResolvedValue(true) }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: 'de-DE', t: key => key.split('.').reduce((value, part) => value?.[part], german) || key }) }));

const row = (id = 'unit-a', label = 'Gartenwohnung') => ({ id, label, property_id: 'property-a', property_name: 'Lindenhof',
  unit_type: 'apartment', status: 'occupied', area_sqm: 72, rooms: 3, cold_rent: 0, service_charge_advance: null,
  heating_advance: 0, active_contract_count: 1, tenant_name: 'Privater Mieter', has_contract: true,
  updated_at: '2026-10-03T00:00:00.000001Z', edit_etag: 'revision-a' });
const page = (items, cursor = null) => ({ items, has_more: Boolean(cursor), next_cursor: cursor });
const summary = { total: 10001, rent_count: 10000, occupied: 9000, vacant: 1001, reserved: 0, multiple_active: 1, average_cold_rent: 710.5 };
const draftPath = '/auth/users/me/form-drafts';
const draftSaved = { revision: 'draft-a', updated_at: '2026-10-03T00:00:00Z', expires_at: '2026-10-10T00:00:00Z' };
const writes = () => mocks.put.mock.calls.filter(([path]) => path.startsWith('/units/'));
const response = path => path.startsWith(draftPath) ? { draft: null } : path === '/units/unit-a' ? { ...row(), features: 'Originale Ausstattung' } : path.includes('/summary?') ? summary : path.startsWith('/workflow-references/')
  ? { ...page([{ id: 'property-a', name: 'Lindenhof' }]), selected: new URLSearchParams(path.split('?')[1]).get('selected_id') ? { id: 'property-a', name: 'Lindenhof' } : null }
  : page([row()]);
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const view = () => render(<MemoryRouter><Units /></MemoryRouter>);

beforeEach(() => {
  Object.values(mocks).forEach(value => value?.mockReset?.());
  mocks.user = { id: 'owner-a', role: 'eigentuemer', portfolio_access: 'all', portfolio_ids: [] };
  mocks.get.mockImplementation(path => Promise.resolve(response(path)));
  mocks.post.mockResolvedValue({}); mocks.put.mockImplementation(path => Promise.resolve(path === draftPath ? draftSaved : {}));
  mocks.del.mockResolvedValue({ discarded: true });
});

describe('bounded unit inventory', () => {
  it('uses full server aggregates, exact joined names, and zero/missing amounts honestly', async () => {
    view();
    await screen.findByRole('link', { name: 'Gartenwohnung' });
    expect(screen.getByRole('region', { name: 'Kennzahlen der gefilterten Einheiten' })).toHaveTextContent('10001');
    expect(screen.getByRole('region', { name: 'Gefilterte Einheiten' })).toHaveTextContent('0,00 €');
    expect(screen.getByText('Angaben unvollständig')).toBeVisible();
    expect(screen.getByText('Privater Mieter')).toBeVisible();
    expect(mocks.get.mock.calls.every(([path]) => path.includes('/inventory/') || path.includes('/workflow-references/'))).toBe(true);
  });

  it('queries filters before pagination, retaining search text on failure and retry', async () => {
    view(); await screen.findByRole('link', { name: 'Gartenwohnung' });
    mocks.get.mockImplementation(path => path.includes('/inventory/page?') ? Promise.reject(new Error('Server vorübergehend nicht erreichbar')) : Promise.resolve(response(path)));
    fireEvent.change(screen.getByRole('searchbox', { name: 'Einheiten durchsuchen' }), { target: { value: 'Wohnung 10001' } });
    expect(await screen.findByText('Server vorübergehend nicht erreichbar')).toBeVisible();
    expect(screen.queryByText('Keine passenden Einheiten auf dieser Seite.')).not.toBeInTheDocument();
    expect(screen.getByRole('searchbox', { name: 'Einheiten durchsuchen' })).toHaveValue('Wohnung 10001');
    expect(mocks.get.mock.calls.some(([path]) => path.includes('search=Wohnung+10001'))).toBe(true);
    mocks.get.mockImplementation(path => Promise.resolve(response(path)));
    await userEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
    expect(await screen.findByRole('link', { name: 'Gartenwohnung' })).toBeVisible();
  });

  it('navigates bounded pages while summary remains independent', async () => {
    mocks.get.mockImplementation(path => Promise.resolve(path.includes('/page?') ? path.includes('cursor=next-token') ? page([row('unit-b', 'Spätere Einheit')]) : page([row()], 'next-token') : response(path)));
    view(); await screen.findByRole('link', { name: 'Gartenwohnung' });
    const before = mocks.get.mock.calls.filter(([path]) => path.includes('/summary?')).length;
    await userEvent.click(screen.getByRole('button', { name: 'Nächste Seite', exact: true }));
    expect(await screen.findByRole('link', { name: 'Spätere Einheit' })).toBeVisible();
    expect(mocks.get.mock.calls.filter(([path]) => path.includes('/summary?')).length).toBe(before);
    await userEvent.click(screen.getByRole('button', { name: 'Vorherige Seite', exact: true }));
    expect(await screen.findByRole('link', { name: 'Gartenwohnung' })).toBeVisible();
  });

  it.each(['user', 'scope', 'role'])('drops names and open forms synchronously on %s change', async kind => {
    const rendered = view(); await screen.findByRole('link', { name: 'Gartenwohnung' });
    await userEvent.click(screen.getByRole('button', { name: 'Gartenwohnung bearbeiten' }));
    const old = mocks.get.mock.calls[0][1].signal;
    mocks.get.mockReturnValue(new Promise(() => {}));
    if (kind === 'user') mocks.user = { ...mocks.user, id: 'owner-b' };
    if (kind === 'scope') mocks.user = { ...mocks.user, portfolio_ids: ['new'] };
    if (kind === 'role') mocks.user = { ...mocks.user, role: 'readonly' };
    rendered.rerender(<MemoryRouter><Units /></MemoryRouter>);
    expect(screen.queryByText('Privater Mieter')).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(old.aborted).toBe(true);
  });

  it('ignores a late result from the previous search', async () => {
    const old = deferred();
    mocks.get.mockImplementation(path => path.includes('/page?') && !path.includes('search=') ? old.promise : Promise.resolve(response(path)));
    view(); fireEvent.change(screen.getByRole('searchbox', { name: 'Einheiten durchsuchen' }), { target: { value: 'Garten' } });
    await screen.findByRole('link', { name: 'Gartenwohnung' });
    await act(async () => old.resolve(page([row('secret', 'Alter privater Name')])));
    expect(screen.queryByText('Alter privater Name')).not.toBeInTheDocument();
  });

  it('keeps independent summary errors visible without turning them into zero', async () => {
    mocks.get.mockImplementation(path => path.includes('/summary?') ? Promise.reject(new Error('Kennzahlenfehler')) : Promise.resolve(response(path)));
    view(); await screen.findByRole('link', { name: 'Gartenwohnung' });
    expect(screen.getByRole('region', { name: 'Kennzahlen der gefilterten Einheiten' })).toHaveTextContent('Kennzahlen nicht verfügbar');
    expect(screen.getByRole('region', { name: 'Kennzahlen der gefilterten Einheiten' })).not.toHaveTextContent('10001');
  });

  it('keeps a form draft and its original revision after a failed write', async () => {
    mocks.put.mockImplementation(path => path === draftPath ? Promise.resolve(draftSaved) : Promise.reject(new Error('Änderung konnte nicht gespeichert werden')));
    view(); await screen.findByRole('link', { name: 'Gartenwohnung' });
    await userEvent.click(screen.getByRole('button', { name: 'Gartenwohnung bearbeiten' }));
    const dialog = await screen.findByRole('dialog');
    await within(dialog).findByText('Entwurfsschutz bereit');
    fireEvent.change(within(dialog).getByLabelText('Bezeichnung *'), { target: { value: 'Mein erhaltener Entwurf' } });
    fireEvent.submit(dialog.querySelector('form'));
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(await within(dialog).findByText('Änderung konnte nicht gespeichert werden')).toBeVisible();
    expect(within(dialog).getByLabelText('Bezeichnung *')).toHaveValue('Mein erhaltener Entwurf');
    expect(writes()[0][1]).toMatchObject({ label: 'Mein erhaltener Entwurf', property_id: 'property-a', cold_rent: 0, features: 'Originale Ausstattung' });
    expect(writes()[0][2].ifMatch.updatedAt).toBe(row().updated_at);
  });

  it('uses full export filters without the current page cursor', async () => {
    mocks.getBlob.mockRejectedValue(new Error('Export fehlgeschlagen'));
    mocks.get.mockImplementation(path => Promise.resolve(path.includes('/page?') ? page([row()], 'next-token') : response(path)));
    view(); await screen.findByRole('link', { name: 'Gartenwohnung' });
    await userEvent.click(screen.getByRole('button', { name: 'Nächste Seite', exact: true }));
    await screen.findByRole('link', { name: 'Gartenwohnung' });
    await userEvent.click(screen.getByRole('button', { name: 'Alle gefilterten Einheiten exportieren' }));
    expect(await screen.findByText('Export fehlgeschlagen')).toBeVisible();
    expect(mocks.getBlob.mock.calls[0][0]).toContain('/units/inventory/export?');
    expect(mocks.getBlob.mock.calls[0][0]).not.toContain('cursor=');
  });
});
