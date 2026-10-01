import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import Bookings from '../pages/Bookings';
import BookingEditor from '../components/BookingEditor';
import { annotateRevisions, EDIT_REVISION } from '../editRevision';
import german from '../../../i18n/de-DE.json';

const mocks = vi.hoisted(() => ({ get: vi.fn(), getAll: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), getBlob: vi.fn(),
  confirm: vi.fn(), invalidateRelated: vi.fn(), role: 'eigentuemer' }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ role: mocks.role, user: { id: 'synthetic-owner', role: mocks.role } }) }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => ({ invalidateRelated: mocks.invalidateRelated }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => mocks.confirm }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: 'de-DE', t: (key, params) => {
  let value = key.split('.').reduce((current, part) => current?.[part], german) || key;
  Object.entries(params || {}).forEach(([name, replacement]) => { value = value.replace(`{{${name}}}`, replacement); });
  return value;
} }) }));
const row = (id, text = id) => ({ id, payment_text: text, account_id: 'selected-account', account_name: 'Selected account',
  booking_date: '2026-10-01', amount: -12.34, status: 'open', updated_at: '2026-10-01T08:00:00.123456' });
const page = (items, next = null) => ({ items, next_cursor: next, has_more: next !== null });
const choices = (id = 'selected-account') => ({ items: [{ id: 'choice-1', label: 'First choice' }], selected: id ? { id, label: `Selected ${id}` } : null,
  next_cursor: null, has_more: false });
let failLookup;
beforeEach(() => {
  vi.clearAllMocks();
  mocks.role = 'eigentuemer'; failLookup = null;
  mocks.confirm.mockResolvedValue(true); mocks.post.mockResolvedValue({}); mocks.put.mockResolvedValue({}); mocks.del.mockResolvedValue({});
  mocks.get.mockImplementation(async path => {
    const url = new URL(path, 'http://localhost');
    if (url.pathname.startsWith('/bookings/lookup/')) {
      if (url.pathname.endsWith(failLookup)) throw new Error('Reference unavailable');
      return choices(url.searchParams.get('selected_id'));
    }
    if (url.pathname === '/bookings/page') return page(url.searchParams.has('cursor') ? [row('last')] : [row('first'), row('second')], url.searchParams.has('cursor') ? null : 'actual-server-cursor');
    throw new Error(`Unexpected GET ${path}`);
  });
});
const editorForm = () => screen.getByRole('dialog').querySelector('form');
const loaded = () => screen.findByRole('button', { name: 'Buchung bearbeiten first', exact: true });

it('confirms a booking only after explicit save with its original revision, then filters confirmed rows', async () => {
  render(<Bookings />);
  await loaded();
  expect(mocks.put).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Buchung bearbeiten first', exact: true }));
  const dialog = screen.getByRole('dialog');
  await waitFor(() => expect(within(dialog).getByRole('button', { name: 'Speichern', exact: true })).toBeEnabled());
  expect(within(dialog).getByLabelText('Status')).toHaveValue('open');
  fireEvent.change(within(dialog).getByLabelText('Status'), { target: { value: 'confirmed' } });
  expect(mocks.put).not.toHaveBeenCalled();
  fireEvent.submit(editorForm());
  await waitFor(() => expect(mocks.put).toHaveBeenCalledOnce());
  expect(mocks.put.mock.calls[0][1].status).toBe('confirmed');
  expect(mocks.put.mock.calls[0][1][EDIT_REVISION]).toMatchObject({ id: 'first', updatedAt: '2026-10-01T08:00:00.123456' });
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'confirmed' } });
  fireEvent.submit(screen.getByRole('button', { name: 'Filter anwenden' }).closest('form'));
  await waitFor(() => expect(mocks.get.mock.calls.some(([path]) => path.includes('status=confirmed'))).toBe(true));
});

it('loads only the requested server page and uses returned cursors for next/back without getAll', async () => {
  render(<Bookings />);
  await loaded();
  expect(mocks.get.mock.calls.filter(([path]) => path.startsWith('/bookings/page'))).toHaveLength(1);
  fireEvent.click(screen.getByRole('button', { name: 'Weiter', exact: true }));
  await screen.findByRole('button', { name: 'Buchung bearbeiten last', exact: true });
  const next = mocks.get.mock.calls.find(([path]) => path.includes('cursor='));
  expect(new URL(next[0], 'http://localhost').searchParams.get('cursor')).toBe('actual-server-cursor');
  expect(screen.queryByText('first', { selector: 'td' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Zurück', exact: true }));
  await loaded();
  expect(mocks.getAll).not.toHaveBeenCalled();
  expect(mocks.get.mock.calls.every(([path]) => path.startsWith('/bookings/page?') || path.startsWith('/bookings/lookup/'))).toBe(true);
});

it('applies a valid account drilldown URL to the initial server page and lookup', async () => {
  const previous = window.location.href;
  window.history.replaceState({}, '', '/bookings?account_id=bank-source');
  try {
    render(<Bookings />);
    await loaded();
    const path = mocks.get.mock.calls.find(([value]) => value.startsWith('/bookings/page'))[0];
    expect(new URL(path, 'http://localhost').searchParams.get('account_id')).toBe('bank-source');
    expect(screen.getByText(german.accountBalance.filteredBookings)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('option', { name: 'Selected bank-source' })).toBeInTheDocument());
    expect(mocks.get.mock.calls.some(([value]) => value.includes('selected_id=bank-source'))).toBe(true);
  } finally { window.history.replaceState({}, '', previous); }
});

it('aborts an obsolete page request and cannot publish its late result after a filter change', async () => {
  let resolveOld;
  const standard = mocks.get.getMockImplementation();
  mocks.get.mockImplementation((path, options) => path.startsWith('/bookings/page?') && !path.includes('search=')
    ? new Promise(resolve => { resolveOld = resolve; }) : standard(path, options));
  render(<Bookings />);
  const originalSignal = mocks.get.mock.calls.find(([path]) => path.startsWith('/bookings/page'))[1].signal;
  fireEvent.change(screen.getByLabelText('Buchungstext oder ID suchen'), { target: { value: 'Miete' } });
  fireEvent.submit(screen.getByRole('button', { name: 'Filter anwenden' }).closest('form'));
  await loaded();
  expect(originalSignal.aborted).toBe(true);
  await act(async () => resolveOld(page([row('stale')])));
  expect(screen.queryByText('stale', { selector: 'td' })).not.toBeInTheDocument();
  expect(mocks.get.mock.calls.some(([path]) => path.includes('search=Miete'))).toBe(true);
});

it('shows recoverable cursor errors and restarts explicitly with the same applied filters', async () => {
  const standard = mocks.get.getMockImplementation();
  mocks.get.mockImplementation((path, options) => path.includes('cursor=') ? Promise.reject(Object.assign(new Error('Expired cursor'), { code: 'cursor_expired' })) : standard(path, options));
  render(<Bookings />);
  fireEvent.change(screen.getByLabelText('Buchungstext oder ID suchen'), { target: { value: 'Text%_literal' } });
  fireEvent.submit(screen.getByRole('button', { name: 'Filter anwenden' }).closest('form'));
  await loaded();
  fireEvent.click(screen.getByRole('button', { name: 'Weiter', exact: true }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Expired cursor');
  const failedCount = mocks.get.mock.calls.filter(([path]) => path.startsWith('/bookings/page')).length;
  await act(async () => {});
  expect(mocks.get.mock.calls.filter(([path]) => path.startsWith('/bookings/page'))).toHaveLength(failedCount);
  fireEvent.click(screen.getByRole('button', { name: 'Ab erster Seite neu laden' }));
  await loaded();
  const lastPath = mocks.get.mock.calls.filter(([path]) => path.startsWith('/bookings/page')).at(-1)[0];
  expect(new URL(lastPath, 'http://localhost').searchParams.get('search')).toBe('Text%_literal');
  expect(lastPath).not.toContain('cursor=');
});

it('preserves page revisions for PUT and DELETE while readonly removes every mutation control', async () => {
  const { rerender } = render(<Bookings />);
  await loaded();
  fireEvent.click(screen.getByRole('button', { name: 'Buchung bearbeiten first', exact: true }));
  await waitFor(() => expect(within(screen.getByRole('dialog')).getByRole('button', { name: 'Speichern', exact: true })).toBeEnabled());
  fireEvent.change(within(screen.getByRole('dialog')).getByLabelText('Buchungstext'), { target: { value: 'Edited draft' } });
  fireEvent.submit(editorForm());
  await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(1));
  expect(mocks.put.mock.calls[0][0]).toBe('/bookings/first');
  expect(mocks.put.mock.calls[0][1][EDIT_REVISION]).toMatchObject({ id: 'first', collection: 'bookings', updatedAt: '2026-10-01T08:00:00.123456' });
  await loaded();
  fireEvent.click(screen.getByRole('button', { name: 'Löschen first', exact: true }));
  await waitFor(() => expect(mocks.del).toHaveBeenCalledTimes(1));
  expect(mocks.del.mock.calls[0][1].ifMatch.collection).toBe('bookings');
  mocks.role = 'readonly'; rerender(<Bookings />);
  expect(screen.queryByRole('button', { name: 'Neu', exact: true })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /^Buchung bearbeiten / })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /^Löschen / })).not.toBeInTheDocument();
});

it('cannot revive an old pending delete confirmation after rights are revoked and granted again', async () => {
  let confirmOld;
  mocks.confirm.mockImplementation(() => new Promise(resolve => { confirmOld = resolve; }));
  const { rerender } = render(<Bookings />);
  await loaded();
  fireEvent.click(screen.getByRole('button', { name: 'Löschen first', exact: true }));
  mocks.role = 'readonly'; rerender(<Bookings />);
  mocks.role = 'eigentuemer'; rerender(<Bookings />);
  await act(async () => confirmOld(true));
  expect(mocks.del).not.toHaveBeenCalled();
});

it('keeps lookup failures visible, prevents saving, and recovers without changing the draft', async () => {
  failLookup = 'accounts';
  render(<BookingEditor initial={row('first')} onSave={mocks.put} onClose={vi.fn()} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Reference unavailable');
  fireEvent.change(screen.getByLabelText('Buchungstext'), { target: { value: 'Kept draft' } });
  fireEvent.submit(editorForm());
  expect(mocks.put).not.toHaveBeenCalled();
  failLookup = null;
  fireEvent.click(screen.getByRole('button', { name: 'Erneut versuchen' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Speichern', exact: true })).toBeEnabled());
  expect(screen.getByLabelText('Buchungstext')).toHaveValue('Kept draft');
  expect(screen.getByRole('combobox', { name: 'Konto *', exact: true })).toHaveValue('selected-account');
});

it('retains a selected FK beyond the lookup page and synchronizes a new server FK after explicit conflict reconciliation', async () => {
  const initial = annotateRevisions(row('first'), '/bookings');
  const current = annotateRevisions({ ...row('first'), account_id: 'remote-account-1103', updated_at: '2026-10-01T09:01:00.654321' }, '/bookings');
  const standard = mocks.get.getMockImplementation();
  mocks.get.mockImplementation((path, options) => path === '/bookings/first' ? Promise.resolve(current) : standard(path, options));
  const save = vi.fn().mockRejectedValueOnce(Object.assign(new Error('Changed'), { isEditConflict: true, resourcePath: '/bookings/first' })).mockResolvedValue({});
  render(<BookingEditor initial={initial} onSave={save} onClose={vi.fn()} />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Speichern', exact: true })).toBeEnabled());
  expect(screen.getByRole('combobox', { name: 'Konto *', exact: true })).toHaveValue('selected-account');
  fireEvent.change(screen.getByLabelText('Buchungstext'), { target: { value: 'My draft' } });
  fireEvent.submit(editorForm());
  fireEvent.click(await screen.findByRole('button', { name: 'Aktuellen Stand prüfen' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Abgleich übernehmen' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Speichern', exact: true })).toBeEnabled());
  expect(screen.getByRole('combobox', { name: 'Konto *', exact: true })).toHaveValue('remote-account-1103');
  expect(screen.getByLabelText('Buchungstext')).toHaveValue('My draft');
  fireEvent.submit(editorForm());
  await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
  expect(save.mock.calls[1][0].account_id).toBe('remote-account-1103');
  expect(save.mock.calls[1][0][EDIT_REVISION].updatedAt).toBe('2026-10-01T09:01:00.654321');
  expect(mocks.get.mock.calls.some(([path]) => path.includes('selected_id=remote-account-1103'))).toBe(true);
});

it('rejects malformed pages instead of presenting successful empty results and retries genuine load failures', async () => {
  const standard = mocks.get.getMockImplementation();
  mocks.get.mockImplementation((path, options) => path.startsWith('/bookings/page?') ? Promise.resolve({ items: [], has_more: true, next_cursor: null }) : standard(path, options));
  render(<Bookings />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Die Serverantwort konnte nicht gelesen werden');
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
  mocks.get.mockImplementation(standard);
  fireEvent.click(screen.getByRole('button', { name: 'Erneut versuchen' }));
  await loaded();
});

it('exports every matching row with only the applied filters and surfaces download failures', async () => {
  mocks.getBlob.mockRejectedValue(new Error('Export unavailable'));
  render(<Bookings />);
  await loaded();
  fireEvent.change(screen.getByLabelText('Buchungstext oder ID suchen'), { target: { value: 'Applied' } });
  fireEvent.submit(screen.getByRole('button', { name: 'Filter anwenden' }).closest('form'));
  await loaded();
  fireEvent.change(screen.getByLabelText('Buchungstext oder ID suchen'), { target: { value: 'Not applied yet' } });
  fireEvent.click(screen.getByRole('button', { name: 'CSV herunterladen' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Export unavailable');
  const params = new URL(mocks.getBlob.mock.calls[0][0], 'http://localhost').searchParams;
  expect(params.get('search')).toBe('Applied');
  expect(params.has('cursor')).toBe(false);
  expect(params.has('page_size')).toBe(false);
});

it('aborts obsolete reference searches and never offers a late choice from the previous search', async () => {
  let resolveOld;
  const standard = mocks.get.getMockImplementation();
  mocks.get.mockImplementation((path, options) => path.includes('/lookup/accounts?') && path.includes('search=old')
    ? new Promise(resolve => { resolveOld = resolve; }) : standard(path, options));
  render(<BookingEditor initial={row('first')} onSave={mocks.put} onClose={vi.fn()} />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Speichern', exact: true })).toBeEnabled());
  const search = screen.getByRole('searchbox', { name: 'Konto suchen', exact: true });
  fireEvent.change(search, { target: { value: 'old' } });
  await waitFor(() => expect(resolveOld).toBeTypeOf('function'));
  const oldSignal = mocks.get.mock.calls.find(([path]) => path.includes('search=old'))[1].signal;
  fireEvent.change(search, { target: { value: 'new' } });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Speichern', exact: true })).toBeEnabled());
  expect(oldSignal.aborted).toBe(true);
  await act(async () => resolveOld({ items: [{ id: 'stale-choice', label: 'Late choice' }], selected: null, has_more: false, next_cursor: null }));
  expect(screen.queryByRole('option', { name: 'Late choice' })).not.toBeInTheDocument();
});

it('renders an actual empty ledger and reports deletion failures without erasing the loaded page', async () => {
  const standard = mocks.get.getMockImplementation();
  mocks.get.mockImplementation((path, options) => path.startsWith('/bookings/page?') ? Promise.resolve(page([])) : standard(path, options));
  const { unmount } = render(<Bookings />);
  await screen.findByText('Keine Buchungen für diese Filter.');
  expect(screen.getByRole('button', { name: 'Neu', exact: true })).toBeEnabled();
  unmount(); mocks.get.mockImplementation(standard);
  mocks.del.mockRejectedValue(new Error('Delete conflict'));
  render(<Bookings />); await loaded();
  fireEvent.click(screen.getByRole('button', { name: 'Löschen first', exact: true }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Delete conflict');
  expect(screen.getByRole('button', { name: 'Buchung bearbeiten first', exact: true })).toBeInTheDocument();
});

it('traverses bounded reference pages using the actual returned cursor and selects a later reference', async () => {
  const standard = mocks.get.getMockImplementation();
  mocks.get.mockImplementation(async (path, options) => {
    if (!path.startsWith('/bookings/lookup/accounts?')) return standard(path, options);
    const params = new URL(path, 'http://localhost').searchParams;
    return { ...choices(params.get('selected_id')), items: params.has('cursor') ? [{ id: 'later-account-1103', label: 'Later account 1103' }] : [{ id: 'choice-1', label: 'First choice' }],
      has_more: !params.has('cursor'), next_cursor: params.has('cursor') ? null : 'actual-reference-cursor' };
  });
  render(<BookingEditor initial={row('first')} onSave={mocks.put} onClose={vi.fn()} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Weitere Auswahl: Konto', exact: true }));
  await screen.findByRole('option', { name: 'Later account 1103' });
  fireEvent.change(screen.getByRole('combobox', { name: 'Konto *', exact: true }), { target: { value: 'later-account-1103' } });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Speichern', exact: true })).toBeEnabled());
  expect(screen.getByRole('combobox', { name: 'Konto *', exact: true })).toHaveValue('later-account-1103');
  fireEvent.submit(editorForm());
  await waitFor(() => expect(mocks.put).toHaveBeenCalledOnce());
  expect(mocks.put.mock.calls[0][0].account_id).toBe('later-account-1103');
  expect(mocks.get.mock.calls.some(([path]) => path.includes('cursor=actual-reference-cursor'))).toBe(true);
  expect(mocks.getAll).not.toHaveBeenCalled();
});
