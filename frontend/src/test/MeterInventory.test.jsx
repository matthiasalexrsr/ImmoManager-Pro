import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import german from '../../../i18n/de-DE.json';
import Meters from '../pages/Meters';

const mocks = vi.hoisted(() => ({ get: vi.fn(), getBlob: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), user: null, confirm: vi.fn() }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: mocks.user }) }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => null }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => mocks.confirm }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: 'de-DE', t: key => key.split('.').reduce((value, part) => value?.[part], german) || key }) }));

const oldRevision = '2026-10-01T00:00:00.123456Z';
const newRevision = '2026-10-03T00:00:00.654321Z';
const page = (items, more = false) => ({ items, has_more: more, next_cursor: more ? 'next' : null });
const draftPath = '/auth/users/me/form-drafts';
const summary = { total: 10002, active: 9000, inactive: 1002, no_reading: 9000, unknown_unit: 1, overdue: 8, due_soon: 3 };
let record, drafts, sequence, customGet;
const identity = values => `${values.collection}:${values.entity_id || 'create'}:${values.form_key || 'crud'}`;
const draftReply = () => ({ revision: `draft-${++sequence}`, updated_at: '2026-10-03T00:00:00Z', expires_at: '2026-10-10T00:00:00Z' });
const business = method => mocks[method].mock.calls.filter(([path]) => !path.startsWith(draftPath));
const pending = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };

beforeEach(() => {
  Object.values(mocks).forEach(value => value?.mockReset?.());
  record = { id: 'meter-a', serial_number: 'M-10000', meter_type: 'district_loop_x', measurement_unit: 'therm-custom', unit_id: 'unit-a', unit_label: 'Originale Einheit', property_id: 'property-a', property_name: 'Originale Immobilie',
    is_active: false, contract_number: 'Exact contract', contract_end_date: '2028-01-01', supplier: 'Originalsupplier', last_reading_id: 'reading-a', last_reading_date: '2026-10-01', last_reading_value: 0, updated_at: oldRevision, edit_etag: 'exact-etag' };
  drafts = new Map(); sequence = 0; customGet = null;
  mocks.user = { id: 'owner', role: 'eigentuemer', portfolio_access: 'all', portfolio_ids: [] };
  mocks.confirm.mockResolvedValue(true);
  mocks.get.mockImplementation(async (path, options) => {
    if (path.startsWith(draftPath)) return { draft: drafts.get(identity(Object.fromEntries(new URLSearchParams(path.split('?')[1])))) || null };
    if (customGet) { const result = await customGet(path, options); if (result !== undefined) return result; }
    if (path.includes('/inventory/page?')) return page([record], true);
    if (path.includes('/summary?')) return summary;
    if (path.startsWith('/meters/inventory/detail/')) return record;
    if (path.includes('/readings/page?')) return page([{ id: 'reading-a', meter_id: record.id, value: 0, reading_date: '2026-10-01', notes: 'Original note' }], true);
    if (path.startsWith('/workflow-references/')) {
      const selected = new URLSearchParams(path.split('?')[1]).get('selected_id');
      return { ...page([{ id: 'unit-b', label: 'Spätere Einheit', property_id: 'property-b' }]), selected: selected ? { id: selected, label: `Geprüft ${selected}` } : null };
    }
    throw new Error(`Unexpected read ${path}`);
  });
  mocks.put.mockImplementation(async (path, data) => {
    if (path !== draftPath) return {};
    const result = draftReply(); drafts.set(identity(data), { ...data, ...result }); return result;
  });
  mocks.del.mockImplementation(async path => { if (path.startsWith(draftPath)) drafts.delete(identity(Object.fromEntries(new URLSearchParams(path.split('?')[1])))); return {}; });
  mocks.post.mockResolvedValue({ id: 'created' });
});

async function edit() {
  await userEvent.click(await screen.findByRole('button', { name: 'M-10000 bearbeiten', exact: true }));
  const dialog = await screen.findByRole('dialog'); await within(dialog).findByText('Entwurfsschutz bereit'); return dialog;
}
async function showReadings() {
  await userEvent.click(await screen.findByRole('button', { name: 'M-10000 Ablesungen anzeigen', exact: true }));
  return screen.findByRole('region', { name: 'Ablesungen des geöffneten Zählers' });
}

describe('bounded meter inventory', () => {
  it('shows complete server counts, last original zero, stable pages and filtered CSV without global readers', async () => {
    mocks.getBlob.mockRejectedValue(new Error('Synthetic export failure'));
    render(<Meters />);
    expect(await screen.findByText('M-10000')).toBeVisible();
    expect(screen.getByRole('region', { name: 'Kennzahlen der gefilterten Zähler' })).toHaveTextContent('10002Zähler gesamt');
    expect(screen.getByRole('region', { name: 'Gefilterte Zähler' })).toHaveTextContent('0');
    await userEvent.click(screen.getByRole('button', { name: 'Nächste Seite', exact: true }));
    await waitFor(() => expect(mocks.get.mock.calls.some(([path]) => path.includes('/inventory/page?') && path.includes('cursor=next'))).toBe(true));
    fireEvent.change(screen.getByLabelText('Zähler durchsuchen'), { target: { value: 'Später Meter' } });
    await waitFor(() => expect(mocks.get.mock.calls.at(-2)[0]).toContain('search=Sp%C3%A4ter+Meter'));
    await userEvent.click(screen.getByRole('button', { name: 'Alle gefilterten Zähler exportieren' }));
    expect(mocks.getBlob.mock.calls[0][0]).toContain('search=Sp%C3%A4ter+Meter');
    expect(mocks.getBlob.mock.calls[0][0]).not.toContain('cursor=');
    expect(await screen.findByText('Synthetic export failure')).toBeVisible();
    expect(mocks.get.mock.calls.every(([path]) => !['/meters', '/meters/readings/all', '/units', '/properties'].includes(path))).toBe(true);
    expect(mocks.get.mock.calls.some(([path]) => path.includes('/readings/page?'))).toBe(false);
  });

  it('loads original readings only on opening, pages one meter and never labels old rows with current units or consumption', async () => {
    render(<Meters />); const region = await showReadings();
    expect(region).toHaveTextContent('Aktuelle Stammdateneinheit:');
    const table = within(region).getByRole('table');
    expect(table).toHaveTextContent('Original note'); expect(table).not.toHaveTextContent('therm-custom');
    expect(within(table).queryByRole('columnheader', { name: 'Verbrauch' })).not.toBeInTheDocument();
    await userEvent.click(within(region).getByRole('button', { name: 'Nächste Ableseseite' }));
    await waitFor(() => expect(mocks.get.mock.calls.some(([path]) => path.includes('/meters/meter-a/readings/page?') && path.includes('cursor=next'))).toBe(true));
    fireEvent.change(within(region).getByLabelText('Ablesedatum von'), { target: { value: '2020-01-01' } });
    await waitFor(() => expect(mocks.get.mock.calls.some(([path]) => path.includes('date_from=2020-01-01') && !path.includes('cursor='))).toBe(true));
  });

  it('keeps reading failure distinct from an empty history and recovers on deliberate reload', async () => {
    customGet = path => { if (path.includes('/readings/page?')) throw new Error('History unavailable'); };
    render(<Meters />); const region = await showReadings();
    expect(await within(region).findByText('History unavailable')).toBeVisible();
    expect(within(region).queryByText('Keine passenden Ablesungen auf dieser Seite.')).not.toBeInTheDocument();
    customGet = path => path.includes('/readings/page?') ? page([]) : undefined;
    await userEvent.click(within(region).getByRole('button', { name: 'Erneut laden' }));
    expect(await within(region).findByText('Keine passenden Ablesungen auf dieser Seite.')).toBeVisible();
  });

  it('uses exact full detail, preserves custom dimensions/status and keeps failed edit input', async () => {
    customGet = path => path.includes('/inventory/page?') ? page([{ ...record, contract_number: 'Projection only' }]) : undefined;
    render(<Meters />); const dialog = await edit();
    expect(within(dialog).getByLabelText('Vertragsnummer')).toHaveValue('Exact contract');
    expect(within(dialog).getByLabelText('Typ *')).toHaveValue('district_loop_x');
    expect(within(dialog).getByLabelText('Tatsächliche Maßeinheit')).toHaveValue('therm-custom');
    expect(within(dialog).getByLabelText('Status')).toHaveValue('false');
    mocks.put.mockImplementation(async (path, data) => { if (path === draftPath) { const result = draftReply(); drafts.set(identity(data), { ...data, ...result }); return result; } throw Object.assign(new Error('Original conflict'), { statusCode: 412 }); });
    fireEvent.change(within(dialog).getByLabelText('Seriennummer'), { target: { value: 'My draft' } }); fireEvent.submit(dialog.querySelector('form'));
    expect(await within(dialog).findByText('Original conflict')).toBeVisible();
    expect(within(dialog).getByLabelText('Seriennummer')).toHaveValue('My draft');
    expect(business('put')[0][1]).toMatchObject({ meter_type: 'district_loop_x', measurement_unit: 'therm-custom', is_active: false });
  });

  it('restores the unit as a real draft field and saves with the original revision after a newer detail arrives', async () => {
    let ui = render(<Meters />); let dialog = await edit();
    fireEvent.change(within(dialog).getByLabelText('Seriennummer'), { target: { value: 'Saved draft' } });
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Spätere Einheit' }));
    await userEvent.click(within(dialog).getByRole('button', { name: 'Abbrechen', exact: true }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(drafts.get('meters:meter-a:crud').values.unit_id).toBe('unit-b');
    ui.unmount(); record = { ...record, updated_at: newRevision }; ui = render(<Meters />);
    await userEvent.click(await screen.findByRole('button', { name: 'M-10000 bearbeiten' })); dialog = await screen.findByRole('dialog');
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Entwurf wiederherstellen', exact: true }));
    expect(within(dialog).getByLabelText('Seriennummer')).toHaveValue('Saved draft');
    expect(mocks.get.mock.calls.some(([path]) => path.includes('selected_id=unit-b'))).toBe(true);
    fireEvent.submit(dialog.querySelector('form'));
    await waitFor(() => expect(business('put')).toHaveLength(1));
    expect(business('put')[0][1].unit_id).toBe('unit-b'); expect(business('put')[0][2].ifMatch.updatedAt).toBe(oldRevision);
    ui.unmount();
  });

  it('keeps an unknown successful reading result pending across reload, preserving meter/date/value without blind retry', async () => {
    mocks.post.mockImplementation(async () => {
      customGet = path => path.includes('/readings/page?') ? page([{ id: 'saved-reading', meter_id: record.id, reading_date: '2026-10-02', value: 124.125, notes: 'Actually saved original' }]) : undefined;
      throw Object.assign(new Error('Lost result'), { statusCode: 503 });
    });
    let ui = render(<Meters />); let region = await showReadings();
    await userEvent.click(within(region).getByRole('button', { name: 'Ablesung erfassen' }));
    let dialog = await screen.findByRole('dialog'); await within(dialog).findByText('Entwurfsschutz bereit');
    fireEvent.change(within(dialog).getByLabelText('Zählerstand *'), { target: { value: '124.125' } });
    fireEvent.change(within(dialog).getByLabelText('Ablesedatum *'), { target: { value: '2026-10-02' } });
    fireEvent.submit(dialog.querySelector('form')); expect(await within(dialog).findByText('Lost result')).toBeVisible();
    fireEvent.submit(dialog.querySelector('form')); expect(business('post')).toHaveLength(1);
    expect(drafts.get('meters/readings:create:meter:meter-a').values).toMatchObject({ meter_id: 'meter-a', reading_date: '2026-10-02', value: '124.125' });
    ui.unmount(); ui = render(<Meters />); region = await showReadings();
    expect(await within(region).findByText('Actually saved original')).toBeVisible();
    await userEvent.click(within(region).getByRole('button', { name: 'Ablesung erfassen' })); dialog = await screen.findByRole('dialog');
    const restoreAfterReview = await within(dialog).findByRole('button', { name: 'Nach Bestandsprüfung weiterbearbeiten', exact: true });
    fireEvent.submit(dialog.querySelector('form')); expect(business('post')).toHaveLength(1);
    expect(within(dialog).getByRole('button', { name: 'Speichern', exact: true })).toBeDisabled();
    await userEvent.click(restoreAfterReview);
    expect(within(dialog).getByLabelText('Zählerstand *')).toHaveValue(124.125);
    expect(within(dialog).getByLabelText('Ablesedatum *')).toHaveValue('2026-10-02');
    expect(dialog.querySelector('input[name="meter_id"]')).toHaveValue('meter-a');
    expect(business('post')).toHaveLength(1);
    ui.unmount();
  });

  it('does not infer unknown meter units on edit or default them from the type', async () => {
    record = { ...record, meter_type: 'cold_water', measurement_unit: null };
    render(<Meters />); expect(await screen.findByText('Ungeklärt')).toBeVisible();
    const dialog = await edit(); expect(within(dialog).getByLabelText('Tatsächliche Maßeinheit')).toHaveValue('');
    fireEvent.submit(dialog.querySelector('form')); await waitFor(() => expect(business('put')).toHaveLength(1));
    expect(business('put')[0][1]).toMatchObject({ meter_type: 'cold_water', measurement_unit: null });
  });

  it('aborts a pending exact detail and hides all old private values immediately on actor or grant change', async () => {
    const detail = pending(); let options;
    customGet = (path, input) => { if (path.startsWith('/meters/inventory/detail/')) { options = input; return detail.promise; } };
    const ui = render(<Meters />); await userEvent.click(await screen.findByRole('button', { name: 'M-10000 bearbeiten' }));
    customGet = path => path.includes('/inventory/page?') ? page([]) : undefined;
    mocks.user = { ...mocks.user, id: 'next-actor', portfolio_ids: ['next'] }; ui.rerender(<Meters />);
    expect(screen.queryByText('M-10000')).not.toBeInTheDocument(); expect(options.signal.aborted).toBe(true);
    await act(async () => detail.resolve(record)); expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('lets readonly actors open bounded readings without creation or edit controls', async () => {
    mocks.user = { ...mocks.user, role: 'readonly' }; render(<Meters />); const region = await showReadings();
    expect(within(region).queryByRole('button', { name: 'Ablesung erfassen' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Zähler anlegen' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'M-10000 bearbeiten' })).not.toBeInTheDocument();
  });

  it('never turns malformed or failed inventory/summary responses into empty data or zero counts', async () => {
    customGet = path => { if (path.includes('/summary?')) throw new Error('Summary unavailable'); if (path.includes('/inventory/page?')) return []; };
    render(<Meters />); expect(await screen.findByText('Die Zählerliste konnte nicht geprüft werden.')).toBeVisible();
    expect(screen.getByRole('region', { name: 'Kennzahlen der gefilterten Zähler' })).toHaveTextContent('Summary unavailable');
    expect(screen.queryByText('Keine passenden Zähler auf dieser Seite.')).not.toBeInTheDocument();
  });
});
