import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import FormModal from '../components/FormModal';
import { api } from '../api';
import { snapshotRevision } from '../editRevision';
import german from '../../../i18n/de-DE.json';

const fixtures = vi.hoisted(() => ({ auth: null }));
const translate = key => key.split('.').reduce((value, part) => value?.[part], german) || key;
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: translate, locale: 'de-DE' }) }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => fixtures.auth }));
vi.mock('../api', () => ({ api: { get: vi.fn(), put: vi.fn(), del: vi.fn() } }));

const fields = [{ key: 'name', label: 'Name', required: true }, { key: 'purchase_price', label: 'Kaufpreis', type: 'number' }];
const initial = { id: 'property-a', name: 'Servername', purchase_price: 100, updated_at: '2026-01-01T10:00:00.123456Z' };
const config = { collection: 'properties' };
const saved = (revision = '00000000-0000-4000-8000-000000000001') => ({ revision, updated_at: '2026-01-01T10:01:00Z', expires_at: '2026-01-08T10:01:00Z' });
const previous = (overrides = {}) => ({ ...saved(), schema: JSON.stringify([['name', 'text'], ['purchase_price', 'number']]),
  values: { name: 'Früherer Entwurf', purchase_price: '123.45' }, original_values: { name: 'Alte Quelle', purchase_price: 100 },
  edit_revision: { collection: 'properties', id: 'property-a', updatedAt: '2025-12-01T12:34:56.654321Z' }, submission_pending: false, ...overrides });
const open = (props = {}) => render(<FormModal title="Immobilie bearbeiten" fields={fields} initial={initial} draftConfig={config}
  onSave={vi.fn()} onClose={vi.fn()} {...props} />);
const ready = () => screen.findByText(translate('formDraft.status.ready'));
const edit = name => fireEvent.change(screen.getByLabelText('Name *'), { target: { value: name } });
const submit = () => fireEvent.submit(screen.getByRole('dialog').querySelector('form'));
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };

beforeEach(() => {
  fixtures.auth = { user: { id: 'user-owner', role: 'eigentuemer', portfolio_access: 'all', portfolio_ids: [] }, canWrite: () => true };
  api.get.mockResolvedValue({ draft: null });
  api.put.mockResolvedValue(saved());
  api.del.mockResolvedValue({ discarded: true });
});
afterEach(() => { vi.clearAllMocks(); vi.useRealTimers(); });

describe('private form draft storage', () => {
  it('leaves non-opted financial/password forms unchanged and makes no draft calls', async () => {
    const onSave = vi.fn();
    open({ draftConfig: undefined, fields: [{ key: 'password', label: 'Passwort', type: 'password' }], initial: null, onSave });
    fireEvent.change(screen.getByLabelText('Passwort'), { target: { value: 'Synthetic passphrase' } });
    submit();
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(api.get).not.toHaveBeenCalled(); expect(api.put).not.toHaveBeenCalled();
  });

  it('autosaves only changed values and never submits the business record', async () => {
    const onSave = vi.fn();
    open({ onSave }); await ready();
    expect(api.put).not.toHaveBeenCalled();
    edit('Mein Entwurf');
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1), { timeout: 2000 });
    const [path, data] = api.put.mock.calls[0];
    expect(path).toBe('/auth/users/me/form-drafts');
    expect(data.owner_id).toBe('user-owner'); expect(data.values.name).toBe('Mein Entwurf');
    expect(data.edit_revision.updatedAt).toBe(initial.updated_at); expect(data.submission_pending).toBe(false);
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByText(translate('formDraft.status.saved'))).toBeVisible();
  });

  it('flushes a pending change on close and retains exact numeric input strings', async () => {
    const onClose = vi.fn(); open({ onClose }); await ready();
    edit('Noch nicht automatisch gesichert');
    fireEvent.change(screen.getByLabelText('Kaufpreis'), { target: { value: '123.45' } });
    fireEvent.click(screen.getByRole('button', { name: 'Abbrechen', exact: true }));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(api.put.mock.calls[0][1].values.purchase_price).toBe('123.45');
  });

  it('offers explicit restore while preserving the original stale business CAS token', async () => {
    api.get.mockResolvedValue({ draft: previous() }); const onSave = vi.fn(); open({ onSave });
    await screen.findByText(translate('formDraft.status.available'));
    expect(screen.getByLabelText('Name *')).toHaveValue('Servername'); expect(api.put).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: translate('formDraft.restore'), exact: true }));
    await waitFor(() => expect(screen.getByLabelText('Name *')).toHaveValue('Früherer Entwurf'));
    expect(onSave).not.toHaveBeenCalled();
    submit(); await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    const version = snapshotRevision(onSave.mock.calls[0][0]);
    expect(version.updatedAt).toBe('2025-12-01T12:34:56.654321Z');
    expect(version.source.name).toBe('Alte Quelle');
    expect(api.get).toHaveBeenCalledTimes(2);
  });

  it('rechecks actual stored revision during restore and does not apply an obsolete copy', async () => {
    api.get.mockResolvedValueOnce({ draft: previous() }).mockResolvedValue({ draft: previous({ ...saved('00000000-0000-4000-8000-000000000002'), values: { name: 'Anderes Fenster', purchase_price: '99' } }) });
    open(); await screen.findByText(translate('formDraft.status.available'));
    fireEvent.click(screen.getByRole('button', { name: translate('formDraft.restore'), exact: true }));
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(3));
    expect(screen.getByLabelText('Name *')).toHaveValue('Servername'); expect(api.put).not.toHaveBeenCalled();
  });

  it('explicit discard retains current values and never saves them back automatically', async () => {
    api.get.mockResolvedValue({ draft: previous() }); open();
    await screen.findByText(translate('formDraft.status.available'));
    edit('Aktuelle Eingabe');
    fireEvent.click(screen.getByRole('button', { name: translate('formDraft.discard'), exact: true }));
    await ready();
    expect(screen.getByLabelText('Name *')).toHaveValue('Aktuelle Eingabe');
    expect(api.del.mock.calls[0][0]).toContain('expected_revision=00000000-0000-4000-8000-000000000001');
    expect(api.put).not.toHaveBeenCalled();
  });

  it('refuses restore for changed form schema instead of silently dropping fields', async () => {
    api.get.mockResolvedValue({ draft: previous({ schema: 'different' }) }); open();
    await screen.findByText(translate('formDraft.status.available'));
    expect(screen.getByRole('button', { name: translate('formDraft.restore') })).toBeDisabled();
    expect(screen.getByRole('alert')).toHaveTextContent(translate('formDraft.schemaChanged'));
    expect(api.put).not.toHaveBeenCalled();
  });

  it('shows storage failure, retains input, and retries only after explicit choice', async () => {
    api.put.mockRejectedValueOnce(Object.assign(new Error('Schlüssel fehlen'), { statusCode: 503 })); open(); await ready();
    edit('Sicher behalten');
    await screen.findByText('Schlüssel fehlen', {}, { timeout: 2000 });
    expect(screen.getByLabelText('Name *')).toHaveValue('Sicher behalten');
    expect(api.put).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Erneut versuchen', exact: true }));
    await screen.findByText(translate('formDraft.status.saved'));
    expect(api.put).toHaveBeenCalledTimes(2);
  });

  it('coalesces in-flight writes and flushes latest values using the returned revision', async () => {
    const pending = deferred(); api.put.mockReturnValueOnce(pending.promise); const onClose = vi.fn(); open({ onClose }); await ready();
    edit('Erste Änderung'); await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1), { timeout: 2000 });
    edit('Letzte Änderung'); fireEvent.click(screen.getByRole('button', { name: 'Abbrechen', exact: true }));
    await act(async () => pending.resolve(saved()));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(api.put).toHaveBeenCalledTimes(2);
    expect(api.put.mock.calls[1][1]).toMatchObject({ expected_revision: saved().revision, values: { name: 'Letzte Änderung' } });
  });

  it('does not replace an existing draft when another window wins its CAS', async () => {
    api.put.mockRejectedValueOnce(Object.assign(new Error('Anderes Fenster'), { statusCode: 409, code: 'DRAFT_CONFLICT' })); open(); await ready(); edit('Mein Stand');
    await screen.findByText('Anderes Fenster', {}, { timeout: 2000 });
    expect(screen.getByLabelText('Name *')).toHaveValue('Mein Stand');
    expect(screen.getByRole('button', { name: translate('formDraft.inspect') })).toBeVisible();
    expect(api.put).toHaveBeenCalledTimes(1);
  });

  it('separates successful business save from failed cleanup and prevents duplicate execution', async () => {
    const onSave = vi.fn(); const onClose = vi.fn(); const onSaved = vi.fn(); api.del.mockRejectedValueOnce(new Error('Cleanup nicht erreichbar')); open({ onSave, onClose, onSaved }); await ready();
    edit('Gespeicherter Datensatz'); submit();
    await screen.findByText(translate('formDraft.businessSaved'));
    expect(onSave).toHaveBeenCalledTimes(1); expect(onClose).not.toHaveBeenCalled();
    expect(onSaved).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Speichern', exact: true })).toBeDisabled();
    expect(api.put.mock.calls[0][1].submission_pending).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: translate('formDraft.cleanupRetry') }));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(api.del).toHaveBeenCalledTimes(2); expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSaved).toHaveBeenCalledTimes(1);
  });

  it('binds a computed card row to its explicit collection without upgrading the original timestamp', async () => {
    open(); await ready(); edit('Berechnete Kartenzeile');
    fireEvent.click(screen.getByRole('button', { name: 'Abbrechen', exact: true }));
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    expect(api.put.mock.calls[0][1].edit_revision).toEqual({ collection: 'properties', id: initial.id, updatedAt: initial.updated_at });
  });

  it('visibly disables business save until draft loading and explicit previous-draft review complete', async () => {
    const pending = deferred(); api.get.mockReturnValueOnce(pending.promise);
    const onSave = vi.fn(); open({ onSave });
    expect(screen.getByRole('button', { name: 'Speichern', exact: true })).toBeDisabled();
    submit(); expect(onSave).not.toHaveBeenCalled();
    await act(async () => pending.resolve({ draft: previous() }));
    await screen.findByText(translate('formDraft.status.available'));
    expect(screen.getByRole('button', { name: 'Speichern', exact: true })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: translate('formDraft.discard') }));
    await ready();
    expect(screen.getByRole('button', { name: 'Speichern', exact: true })).toBeEnabled();
    expect(onSave).not.toHaveBeenCalled();
  });

  it('retains unknown business outcome until deliberate record review', async () => {
    const onSave = vi.fn().mockRejectedValue(new Error('Netzwerk unterbrochen')); open({ onSave }); await ready(); edit('Unbekannter Ausgang'); submit();
    await screen.findByText(translate('formDraft.status.uncertain'));
    expect(screen.getByRole('button', { name: 'Speichern', exact: true })).toBeDisabled();
    expect(api.put.mock.calls[0][1].submission_pending).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: translate('formDraft.restoreAfterReview') }));
    await screen.findByText(translate('formDraft.status.saved'));
    expect(api.put.mock.calls[1][1].submission_pending).toBe(false);
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it('makes pending create recovery visibly require checking for already created records', async () => {
    api.get.mockResolvedValue({ draft: previous({ edit_revision: null, submission_pending: true }) }); open({ initial: null });
    await screen.findByText(translate('formDraft.pendingRestore'));
    expect(screen.getByRole('button', { name: translate('formDraft.restoreAfterReview') })).toBeVisible();
    expect(api.put).not.toHaveBeenCalled();
  });

  it('keeps revision precision and readonly source fields across restore and background refresh', async () => {
    api.get.mockResolvedValue({ draft: previous({ original_values: { name: 'Original', purchase_price: 100, status: 'partially_paid' } }) });
    const onSave = vi.fn(); const view = open({ draftConfig: { ...config, snapshotFields: ['status'] }, onSave });
    await screen.findByText(translate('formDraft.status.available'));
    fireEvent.click(screen.getByRole('button', { name: translate('formDraft.restore') }));
    await screen.findByText(translate('formDraft.status.restored'));
    view.rerender(<FormModal title="Immobilie bearbeiten" fields={fields} initial={{ ...initial, updated_at: '2026-02-02T00:00:00.999999Z' }} draftConfig={{ ...config, snapshotFields: ['status'] }} onSave={onSave} onClose={vi.fn()} />);
    submit(); await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(snapshotRevision(onSave.mock.calls[0][0]).source.status).toBe('partially_paid');
    expect(snapshotRevision(onSave.mock.calls[0][0]).updatedAt).toBe('2025-12-01T12:34:56.654321Z');
  });

  it('ignores delayed data after switching authenticated account and binds the next request to it', async () => {
    const old = deferred(); api.get.mockReturnValueOnce(old.promise).mockResolvedValue({ draft: null });
    const view = open();
    fixtures.auth = { user: { id: 'different-user', role: 'verwalter', portfolio_access: 'selected', portfolio_ids: ['new-portfolio'] }, canWrite: () => true };
    view.rerender(<FormModal title="Immobilie bearbeiten" fields={fields} initial={{ ...initial, id: 'other-property' }} draftConfig={config} onSave={vi.fn()} onClose={vi.fn()} />);
    await ready(); await act(async () => old.resolve({ draft: previous() }));
    expect(screen.queryByText(translate('formDraft.status.available'))).not.toBeInTheDocument();
    edit('Neue Anmeldung'); fireEvent.click(screen.getByRole('button', { name: 'Abbrechen', exact: true }));
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    expect(api.put.mock.calls[0][1]).toMatchObject({ owner_id: 'different-user', entity_id: 'other-property' });
  });
});
