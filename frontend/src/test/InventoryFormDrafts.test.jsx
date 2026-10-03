import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import german from '../../../i18n/de-DE.json';
import Units from '../pages/Units';
import Documents from '../pages/Documents';
import Maintenance from '../pages/Maintenance';

const mocks = vi.hoisted(() => ({ get: vi.fn(), getBlob: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), user: null }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: mocks.user }) }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => null }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => vi.fn().mockResolvedValue(true) }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: 'de-DE', t: key => key.split('.').reduce((value, part) => value?.[part], german) || key }) }));

const draftPath = '/auth/users/me/form-drafts';
const oldRevision = '2026-10-01T00:00:00.123456Z';
const newRevision = '2026-10-03T00:00:00.654321Z';
const rawAppointment = '2026-10-04T15:30:45.123456+00:00';
const page = items => ({ items, has_more: false, next_cursor: null });
const cases = [
  { collection: 'units', Component: Units, nameKey: 'label', field: 'Bezeichnung *', edit: 'Original bearbeiten', create: 'Einheit anlegen',
    summary: { total: 1, rent_count: 1, occupied: 0, vacant: 1, reserved: 0, multiple_active: 0 },
    extra: { unit_type: 'apartment', status: 'vacant', floor: '2', features: 'Originale Ausstattung', cold_rent: 0 } },
  { collection: 'documents', Component: Documents, nameKey: 'title', field: 'Titel *', edit: 'Original bearbeiten', create: 'Dokument erstellen',
    summary: { total: 1, with_file: 1, analyzed: 0, no_assignment: 0 },
    extra: { document_type: 'Rechnung', file_url: '/uploads/documents/original.pdf', description: 'Originaler Dokumenttext', unit_id: 'unit-a', contract_id: 'contract-a' } },
  { collection: 'maintenance', Component: Maintenance, nameKey: 'title', field: 'Titel *', edit: 'Original bearbeiten', create: 'Wartungsfall anlegen',
    summary: { total: 1, open: 1, in_progress: 0, overdue: 0, no_appointment: 0, no_assignee: 0 },
    extra: { category: 'Heizung', priority: 'high', status: 'open', appointment_at: rawAppointment, estimated_cost: 0, unit_id: 'unit-a', description: 'Originaler Falltext' } },
];
let stored;
let currentRecord;
let sequence;
const identity = params => `${params.collection}:${params.entity_id || 'create'}`;
const draftResult = () => ({ revision: `draft-${++sequence}`, updated_at: '2026-10-03T00:00:00Z', expires_at: '2026-10-10T00:00:00Z' });
const businessWrites = collection => mocks.put.mock.calls.filter(([path]) => path.startsWith(`/${collection}/`));
const renderCase = item => render(<MemoryRouter>{createElement(item.Component)}</MemoryRouter>);

function setup(item) {
  currentRecord = { id: 'record-a', [item.nameKey]: 'Original', property_id: 'property-a', property_name: 'Originale Immobilie', updated_at: oldRevision, ...item.extra };
  mocks.get.mockImplementation(async path => {
    if (path.startsWith(draftPath)) return { draft: stored.get(identity(Object.fromEntries(new URLSearchParams(path.split('?')[1])))) || null };
    if (path.startsWith('/workflow-references/')) {
      const kind = path.split('/')[2].split('?')[0];
      const row = kind === 'properties' ? { id: 'property-b', name: 'Spätere Immobilie' }
        : kind === 'units' ? { id: 'unit-b', label: 'Spätere Einheit', property_id: 'property-b' }
          : { id: 'contract-b', contract_number: 'Späterer Vertrag', property_id: 'property-b', unit_id: 'unit-b' };
      const selectedId = new URLSearchParams(path.split('?')[1]).get('selected_id');
      return { ...page([row]), selected: selectedId ? { ...row, id: selectedId, name: `Geprüft ${selectedId}` } : null };
    }
    if (path.includes('/summary?')) return item.summary;
    if (path.includes('/inventory/page?')) return page([currentRecord]);
    return currentRecord;
  });
}
async function openEdit(item) {
  await userEvent.click(await screen.findByRole('button', { name: item.edit, exact: true }));
  return screen.findByRole('dialog');
}
async function chooseReferences(dialog, item) {
  await userEvent.click(await within(dialog).findByRole('button', { name: 'Spätere Immobilie', exact: true }));
  if (item.collection !== 'units') await userEvent.click(await within(dialog).findByRole('button', { name: 'Spätere Einheit', exact: true }));
  if (item.collection === 'documents') await userEvent.click(await within(dialog).findByRole('button', { name: 'Späterer Vertrag', exact: true }));
}
beforeEach(() => {
  Object.values(mocks).forEach(value => value?.mockReset?.());
  stored = new Map(); sequence = 0;
  mocks.user = { id: 'owner', role: 'eigentuemer', portfolio_access: 'all', portfolio_ids: [] };
  mocks.put.mockImplementation(async (path, data) => {
    if (path !== draftPath) return {};
    const result = draftResult(); stored.set(identity(data), { ...data, ...result }); return result;
  });
  mocks.del.mockImplementation(async path => { stored.delete(identity(Object.fromEntries(new URLSearchParams(path.split('?')[1])))); return { discarded: true }; });
  mocks.post.mockResolvedValue({ id: 'created' });
});

describe('inventory drafts share the existing private form lifecycle', () => {
  it('units restores legacy create draft types without coercing historical values', async () => {
    const item = cases[0]; setup(item); let ui = renderCase(item);
    await userEvent.click(await screen.findByRole('button', { name: item.create, exact: true }));
    let dialog = await screen.findByRole('dialog'); await within(dialog).findByText('Entwurfsschutz bereit');
    fireEvent.change(within(dialog).getByLabelText(item.field), { target: { value: 'Historischer Entwurf' } });
    await userEvent.selectOptions(within(dialog).getByLabelText('Art *'), 'Wohnung');
    await chooseReferences(dialog, item);
    await userEvent.click(within(dialog).getByRole('button', { name: 'Abbrechen', exact: true }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(stored.get('units:create').values.unit_type).toBe('Wohnung');
    ui.unmount(); ui = renderCase(item);
    await userEvent.click(await screen.findByRole('button', { name: item.create, exact: true })); dialog = await screen.findByRole('dialog');
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Entwurf wiederherstellen', exact: true }));
    expect(within(dialog).getByLabelText('Art *')).toHaveValue('Wohnung');
    fireEvent.submit(dialog.querySelector('form'));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith('/units', expect.objectContaining({ unit_type: 'Wohnung', label: 'Historischer Entwurf', property_id: 'property-b' })));
    ui.unmount();
  });

  it.each(cases)('$collection restores edited references and protects the saved original revision', async item => {
    setup(item); let ui = renderCase(item); let dialog = await openEdit(item);
    await within(dialog).findByText('Entwurfsschutz bereit');
    fireEvent.change(within(dialog).getByLabelText(item.field), { target: { value: 'Mein Entwurf' } });
    await chooseReferences(dialog, item);
    await userEvent.click(within(dialog).getByRole('button', { name: 'Abbrechen', exact: true }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    const draft = stored.get(`${item.collection}:record-a`);
    expect(draft.values.property_id).toBe('property-b');
    if (item.collection !== 'units') expect(draft.values.unit_id).toBe('unit-b');
    if (item.collection === 'documents') expect(draft.values.contract_id).toBe('contract-b');
    if (item.collection === 'maintenance') expect(draft.original_values.appointment_at).toBe(rawAppointment);
    ui.unmount(); currentRecord = { ...currentRecord, updated_at: newRevision, appointment_at: '2026-10-05T10:00:00Z' };
    ui = renderCase(item); dialog = await openEdit(item);
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Entwurf wiederherstellen', exact: true }));
    await waitFor(() => expect(within(dialog).getByLabelText(item.field)).toHaveValue('Mein Entwurf'));
    expect(mocks.get.mock.calls.some(([path]) => path.includes('selected_id=property-b'))).toBe(true);
    if (item.collection === 'maintenance') expect(within(dialog).getByLabelText('Termin mit Uhrzeit').value).toMatch(/^2026-10-04T15:30:45(?:\.000)?$/);
    mocks.put.mockImplementation(async (path, data) => {
      if (path === draftPath) { const result = draftResult(); stored.set(identity(data), { ...data, ...result }); return result; }
      throw Object.assign(new Error('Der Originalstand wurde inzwischen geändert.'), { statusCode: 412 });
    });
    fireEvent.submit(dialog.querySelector('form'));
    expect(await within(dialog).findByText('Der Originalstand wurde inzwischen geändert.')).toBeVisible();
    expect(within(dialog).getByLabelText(item.field)).toHaveValue('Mein Entwurf');
    const [, payload, options] = businessWrites(item.collection)[0];
    expect(options.ifMatch.updatedAt).toBe(oldRevision);
    expect(payload.property_id).toBe('property-b');
    if (item.collection === 'documents') expect(payload).toMatchObject({ unit_id: 'unit-b', contract_id: 'contract-b', file_url: '/uploads/documents/original.pdf', description: 'Originaler Dokumenttext' });
    if (item.collection === 'maintenance') expect(payload).toMatchObject({ unit_id: 'unit-b', appointment_at: rawAppointment, description: 'Originaler Falltext', estimated_cost: 0 });
    ui.unmount();
  });

  it('documents restores a create draft file reference after all upload screen state is gone', async () => {
    const item = cases[1]; setup(item); const upload = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ file_url: '/uploads/documents/draft.txt' }) });
    vi.stubGlobal('fetch', upload);
    let ui = renderCase(item); await userEvent.click(await screen.findByRole('button', { name: item.create, exact: true }));
    let dialog = await screen.findByRole('dialog'); await within(dialog).findByText('Entwurfsschutz bereit');
    fireEvent.change(within(dialog).getByLabelText(item.field), { target: { value: 'Dateientwurf' } });
    fireEvent.change(within(dialog).getByLabelText('Datei auswählen'), { target: { files: [new File(['synthetic'], 'draft.txt', { type: 'text/plain' })] } });
    await within(dialog).findByText('Die hochgeladene Originaldatei ist für dieses Dokument vorgemerkt.');
    await chooseReferences(dialog, item);
    await userEvent.click(within(dialog).getByRole('button', { name: 'Abbrechen', exact: true }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(stored.get('documents:create').values.file_url).toBe('/uploads/documents/draft.txt');
    ui.unmount(); ui = renderCase(item);
    await userEvent.click(await screen.findByRole('button', { name: item.create, exact: true }));
    dialog = await screen.findByRole('dialog');
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Entwurf wiederherstellen', exact: true }));
    await within(dialog).findByText('Die hochgeladene Originaldatei ist für dieses Dokument vorgemerkt.');
    fireEvent.submit(dialog.querySelector('form'));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith('/documents', expect.objectContaining({ title: 'Dateientwurf', property_id: 'property-b', unit_id: 'unit-b', contract_id: 'contract-b', file_url: '/uploads/documents/draft.txt' })));
    expect(upload).toHaveBeenCalledTimes(1);
    ui.unmount(); vi.unstubAllGlobals();
  });

  it.each(cases)('$collection removes a pending draft read when actor grants change', async item => {
    setup(item); let resolve; const pending = new Promise(done => { resolve = done; });
    const ordinaryGet = mocks.get.getMockImplementation();
    mocks.get.mockImplementation(path => path.startsWith(draftPath) ? pending : ordinaryGet(path));
    const ui = renderCase(item); await openEdit(item);
    const signal = mocks.get.mock.calls.find(([path]) => path.startsWith(draftPath))[1].signal;
    mocks.user = { ...mocks.user, write_permissions: ['other-resource'] };
    ui.rerender(<MemoryRouter><item.Component /></MemoryRouter>);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument(); expect(signal.aborted).toBe(true);
    await act(async () => resolve({ draft: { revision: 'old-private-draft', values: { title: 'Alter privater Entwurf' } } }));
    expect(screen.queryByText('Alter privater Entwurf')).not.toBeInTheDocument();
    expect(mocks.put).not.toHaveBeenCalled();
  });
});
