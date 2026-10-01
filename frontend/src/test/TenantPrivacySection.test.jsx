import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import TenantPrivacySection from '../components/TenantPrivacySection';

const mocks = vi.hoisted(() => ({ auth: {}, get: vi.fn(), getBlob: vi.fn(), post: vi.fn() }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => mocks.auth }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key }) }));
vi.mock('../api', () => ({ api: { get: mocks.get, getBlob: mocks.getBlob, post: mocks.post } }));

const tenants = [{ id: 'synthetic-tenant', full_name: 'Synthetic Person', archived: false }];
const preview = { tenant_id: tenants[0].id, scope: 'tenant_profile_only', plan_hash: 'a'.repeat(64),
  can_anonymize: true, active_contracts: 0, retained_collections: { contracts: 1, payments: 2 },
  note: 'Unterlagen und Finanzbelege bleiben erhalten.' };

beforeEach(() => {
  vi.clearAllMocks();
  mocks.auth = { user: { id: 'owner', role: 'eigentuemer', write_permissions: ['administration'] } };
  mocks.get.mockResolvedValue(preview);
  mocks.post.mockResolvedValue({ status: 'profile_anonymized' });
});
afterEach(() => { vi.restoreAllMocks(); });

const select = () => {
  screen.getByLabelText('Mieter auswählen').closest('details').open = true;
  fireEvent.change(screen.getByLabelText('Mieter auswählen'), { target: { value: tenants[0].id } });
};
const load = async () => {
  select(); fireEvent.click(screen.getByRole('button', { name: 'Anonymisierung prüfen' }));
  await screen.findByText('Geprüfter Umfang: Mieterstammdaten');
};

describe('tenant privacy workflow', () => {
  it.each(['readonly', 'techniker', 'buchhaltung'])('offers no administration requests to %s', role => {
    mocks.auth = { user: { role } };
    const { container } = render(<TenantPrivacySection tenants={tenants} />);
    expect(container).toBeEmptyDOMElement(); expect(mocks.get).not.toHaveBeenCalled();
  });

  it('requires a reviewed snapshot and exact name before the destructive profile command', async () => {
    const onUpdated = vi.fn(); render(<TenantPrivacySection tenants={tenants} onUpdated={onUpdated} />);
    expect(screen.getByRole('button', { name: 'Anonymisierung prüfen' })).toBeDisabled();
    await load();
    expect(screen.getByText('Zahlungsbelege')).toBeVisible();
    const submit = screen.getByRole('button', { name: 'Stammdaten anonymisieren' });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Bestätigung: vollständigen Namen eingeben'), { target: { value: 'Wrong Person' } });
    expect(submit).toBeDisabled(); expect(mocks.post).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('Bestätigung: vollständigen Namen eingeben'), { target: { value: tenants[0].full_name } });
    fireEvent.click(submit);
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith('/admin/dsgvo/tenant/synthetic-tenant/anonymize',
      { plan_hash: preview.plan_hash, confirm_tenant_id: tenants[0].id }, { signal: expect.any(AbortSignal) }));
    expect(await screen.findByRole('status')).toHaveTextContent('bleiben erhalten');
    expect(onUpdated).toHaveBeenCalledOnce();
  });

  it('shows remaining active contracts and offers no anonymization submission', async () => {
    mocks.get.mockResolvedValue({ ...preview, can_anonymize: false, active_contracts: 2 });
    render(<TenantPrivacySection tenants={tenants} />); await load();
    expect(screen.getByRole('status')).toHaveTextContent('2 aktive Mietverträge');
    expect(screen.queryByRole('button', { name: 'Stammdaten anonymisieren' })).not.toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('preserves the typed draft on a stale review conflict and reports no success', async () => {
    mocks.post.mockRejectedValue(new Error('Der geprüfte Datenstand hat sich geändert.'));
    const onUpdated = vi.fn(); render(<TenantPrivacySection tenants={tenants} onUpdated={onUpdated} />); await load();
    const input = screen.getByLabelText('Bestätigung: vollständigen Namen eingeben');
    fireEvent.change(input, { target: { value: tenants[0].full_name } });
    fireEvent.click(screen.getByRole('button', { name: 'Stammdaten anonymisieren' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Datenstand');
    expect(input).toHaveValue(tenants[0].full_name); expect(onUpdated).not.toHaveBeenCalled();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('rejects an incomplete preview rather than allowing an unreviewed command', async () => {
    mocks.get.mockResolvedValue(null);
    render(<TenantPrivacySection tenants={tenants} />); select();
    fireEvent.click(screen.getByRole('button', { name: 'Anonymisierung prüfen' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Ungültige');
    expect(screen.queryByRole('button', { name: 'Stammdaten anonymisieren' })).not.toBeInTheDocument();
  });

  it('aborts a pending private response when session write rights are revoked', async () => {
    let resolve; mocks.get.mockImplementation(() => new Promise(done => { resolve = done; }));
    const view = render(<TenantPrivacySection tenants={tenants} />); select();
    fireEvent.click(screen.getByRole('button', { name: 'Anonymisierung prüfen' }));
    const signal = mocks.get.mock.calls[0][1].signal;
    mocks.auth = { user: { id: 'owner', role: 'eigentuemer', write_permissions: [] } };
    view.rerender(<TenantPrivacySection tenants={tenants} />);
    expect(signal.aborted).toBe(true);
    await act(async () => resolve(preview));
    expect(view.container).toBeEmptyDOMElement(); expect(mocks.post).not.toHaveBeenCalled();
  });
});
