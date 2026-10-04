import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import german from '../../../i18n/de-DE.json';
import Contacts from '../pages/Contacts';

const mocks = vi.hoisted(() => ({ get: vi.fn(), getBlob: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), user: null }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: mocks.user }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => vi.fn().mockResolvedValue(true) }));
vi.mock('../hooks/useFormDraft', () => ({ default: () => ({ enabled: false, status: 'disabled' }) }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: 'de-DE', t: key => key.split('.').reduce((value, part) => value?.[part], german) || key }) }));
const row = (id = 'contact-a', name = 'Werkstatt Müller') => ({ id, display_name: name, company_name: name, contact_type: 'supplier', first_name: null, last_name: null,
  email: 'synthetic@example.test', phone: '0123', mobile: '0456', city: 'Kassel', zip_code: '34117', country: 'AT',
  updated_at: '2026-10-03T00:00:00.000001Z', edit_etag: 'contact-revision' });
const page = (items, cursor = null) => ({ items, has_more: Boolean(cursor), next_cursor: cursor });
const totals = { total: 10002, tenant: 1, owner: 1, supplier: 9999, manager: 1, no_email: 301, no_phone: 12 };
const response = path => path.includes('/summary?') ? totals : path.startsWith('/contacts/inventory/') ? page([row()])
  : { ...row(), notes: 'Vollständige private Notiz', iban: 'ORIGINAL-IBAN', bic: 'ORIGINAL-BIC', bank_name: 'Hausbank', tax_id: 'ORIGINAL-TAX', street: 'Gartenstraße' };
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };

beforeEach(() => {
  Object.values(mocks).forEach(value => value?.mockReset?.());
  mocks.user = { id: 'owner', role: 'eigentuemer', portfolio_access: 'all', portfolio_ids: [] };
  mocks.get.mockImplementation(path => Promise.resolve(response(path)));
});

describe('bounded complete contact inventory', () => {
  it('shows all matching counts and only projected contact data', async () => {
    render(<Contacts />); await screen.findByText('Werkstatt Müller');
    expect(screen.getByRole('region', { name: 'Kennzahlen der gefilterten Kontakte' })).toHaveTextContent('10002');
    expect(screen.getByRole('table')).toHaveTextContent('synthetic@example.test');
    expect(screen.getByRole('table')).not.toHaveTextContent('ORIGINAL-IBAN');
    expect(mocks.get.mock.calls.every(([path]) => path.includes('/inventory/'))).toBe(true);
  });

  it('reaches later pages and preserves failed search without claiming empty stock', async () => {
    mocks.get.mockImplementation(path => path.includes('search=Ausfall') ? Promise.reject(new Error('Kontaktserver nicht erreichbar')) : Promise.resolve(path.includes('/page?')
      ? path.includes('cursor=later') ? page([row('later', 'Späterer Kontakt')]) : page([row()], 'later') : response(path)));
    render(<Contacts />); await screen.findByText('Werkstatt Müller');
    await userEvent.click(screen.getByRole('button', { name: 'Nächste Seite', exact: true }));
    expect(await screen.findByText('Späterer Kontakt')).toBeVisible();
    fireEvent.change(screen.getByRole('searchbox', { name: 'Kontakte durchsuchen' }), { target: { value: 'Ausfall' } });
    await screen.findAllByText(/Kontaktserver nicht erreichbar/);
    expect(screen.getByRole('searchbox', { name: 'Kontakte durchsuchen' })).toHaveValue('Ausfall');
    expect(screen.queryByText('Keine passenden Kontakte auf dieser Seite.')).not.toBeInTheDocument();
  });

  it('loads exact full contact and preserves bank, country, notes and original revision after failure', async () => {
    mocks.put.mockRejectedValue(new Error('Kontakt konnte nicht gespeichert werden'));
    render(<Contacts />); await screen.findByText('Werkstatt Müller');
    await userEvent.click(screen.getByRole('button', { name: 'Werkstatt Müller bearbeiten' }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByLabelText('Notizen')).toHaveValue('Vollständige private Notiz');
    expect(within(dialog).getByLabelText('BIC')).toHaveValue('ORIGINAL-BIC');
    expect(within(dialog).getByLabelText('Land')).toHaveValue('AT');
    fireEvent.change(within(dialog).getByLabelText('Firma'), { target: { value: 'Erhaltener Firmenname' } });
    fireEvent.submit(dialog.querySelector('form'));
    expect(await within(dialog).findByText('Kontakt konnte nicht gespeichert werden')).toBeVisible();
    expect(within(dialog).getByLabelText('Firma')).toHaveValue('Erhaltener Firmenname');
    expect(mocks.put.mock.calls[0][1]).toMatchObject({ notes: 'Vollständige private Notiz', iban: 'ORIGINAL-IBAN', bic: 'ORIGINAL-BIC', country: 'AT', tax_id: 'ORIGINAL-TAX' });
    expect(mocks.put.mock.calls[0][2].ifMatch.updatedAt).toBe(row().updated_at);
  });

  it.each(['user', 'scope', 'role'])('drops private list and pending contact details on %s change', async kind => {
    const rendered = render(<Contacts />); await screen.findByText('Werkstatt Müller');
    const pending = deferred(); mocks.get.mockImplementation(path => path === '/contacts/contact-a' ? pending.promise : new Promise(() => {}));
    await userEvent.click(screen.getByRole('button', { name: 'Werkstatt Müller bearbeiten' }));
    const signal = mocks.get.mock.calls.find(([path]) => path === '/contacts/contact-a')[1].signal;
    if (kind === 'user') mocks.user = { ...mocks.user, id: 'other' };
    if (kind === 'scope') mocks.user = { ...mocks.user, portfolio_ids: ['other'] };
    if (kind === 'role') mocks.user = { ...mocks.user, role: 'readonly' };
    rendered.rerender(<Contacts />);
    expect(screen.queryByText('Werkstatt Müller')).not.toBeInTheDocument(); expect(signal.aborted).toBe(true);
    await act(async () => pending.resolve(response('/contacts/contact-a')));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('rejects an old page after changing filters', async () => {
    const old = deferred(); mocks.get.mockImplementation(path => path.includes('/page?') && !path.includes('search=') ? old.promise : Promise.resolve(response(path)));
    render(<Contacts />); fireEvent.change(screen.getByRole('searchbox', { name: 'Kontakte durchsuchen' }), { target: { value: 'Neu' } });
    await screen.findByText('Werkstatt Müller');
    await act(async () => old.resolve(page([row('old', 'Alter privater Kontakt')])));
    expect(screen.queryByText('Alter privater Kontakt')).not.toBeInTheDocument();
  });

  it('keeps invalid detail responses out of the editor', async () => {
    mocks.get.mockImplementation(path => Promise.resolve(path === '/contacts/contact-a' ? row('wrong', 'Wrong contact') : response(path)));
    render(<Contacts />); await screen.findByText('Werkstatt Müller');
    await userEvent.click(screen.getByRole('button', { name: 'Werkstatt Müller bearbeiten' }));
    expect(await screen.findByText('Der Kontakt konnte nicht geprüft werden.')).toBeVisible();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('exports the full query and keeps filters on interruption', async () => {
    mocks.getBlob.mockRejectedValue(new Error('Export unterbrochen'));
    render(<Contacts />); await screen.findByText('Werkstatt Müller');
    fireEvent.change(screen.getByRole('searchbox', { name: 'Kontakte durchsuchen' }), { target: { value: 'Werkstatt' } });
    await userEvent.click(screen.getByRole('button', { name: 'Alle gefilterten Kontakte exportieren' }));
    expect(await screen.findByText('Export unterbrochen')).toBeVisible();
    expect(mocks.getBlob.mock.calls[0][0]).toContain('search=Werkstatt');
    expect(mocks.getBlob.mock.calls[0][0]).not.toContain('cursor=');
  });
});
