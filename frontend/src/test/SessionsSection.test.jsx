import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import SessionsSection from '../pages/settings/SessionsSection';
import Settings from '../pages/Settings';
import de from '../../../i18n/de-DE.json';
import en from '../../../i18n/en-US.json';
import es from '../../../i18n/es-ES.json';

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), logout: vi.fn(), confirm: vi.fn(), clearUser: vi.fn(), locale: 'de-DE', t: null, auth: null }));
vi.mock('../api', () => ({ api: { get: mocks.get, post: mocks.post }, logout: mocks.logout }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: mocks.t, locale: mocks.locale }) }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => mocks.auth }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => mocks.confirm }));
vi.mock('../contexts/PreferencesContext', () => ({ usePreferences: () => ({ prefs: {} }) }));
vi.mock('../contexts/DevModeContext', () => ({ useDevMode: () => ({ enabled: false }) }));
vi.mock('../pages/settings/TwoFactorSection', () => ({ default: () => <p>Authenticator</p> }));
vi.mock('../pages/settings/UserManagementSection', () => ({ default: () => null }));
vi.mock('../pages/settings/BackupSection', () => ({ default: () => null }));
vi.mock('../pages/settings/UpdateSection', () => ({ default: () => null }));
vi.mock('../pages/settings/AutotestSection', () => ({ default: () => null }));

const catalogs = { 'de-DE': de, 'en-US': en, 'es-ES': es };
const labels = de.auth.sessions;
const translated = (key, params = {}) => {
  let value = key.split('.').reduce((object, part) => object?.[part], catalogs[mocks.locale]) || key;
  for (const [name, replacement] of Object.entries(params)) value = value.replaceAll(`{{${name}}}`, replacement);
  return value;
};
const row = (changes = {}) => ({ id: 'current', device_label: 'Edge / Windows', current: true, status: 'active',
  created_at: '2026-10-01T10:00:00+00:00', last_used_at: '2026-10-01T11:00:00+00:00',
  expires_at: '2026-10-15T10:00:00+00:00', revoked_at: null, revoke_reason: null, ...changes });
const envelope = (items = [row()], changes = {}) => ({ items, total: items.length, offset: 0, limit: 20,
  current_session_id: 'current', legacy_current: false, persistent: true, ...changes });
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const other = () => row({ id: 'other', device_label: 'Firefox / Linux', current: false });

beforeEach(() => {
  mocks.locale = 'de-DE'; mocks.t = translated;
  mocks.auth = { user: { id: 'viewer', role: 'readonly' }, role: 'readonly', isAdmin: false, clearUser: mocks.clearUser };
  mocks.get.mockReset().mockResolvedValue(envelope([row(), other()]));
  mocks.post.mockReset().mockImplementation(async path => row({ id: path.split('/').at(-2), current: path.includes('/current/'), status: 'revoked', revoked_at: '2026-10-01T12:00:00+00:00', revoke_reason: 'user_revoke' }));
  mocks.logout.mockReset().mockResolvedValue(undefined); mocks.clearUser.mockReset();
  mocks.confirm.mockReset().mockResolvedValue(true);
});

describe('own account sessions', () => {
  it.each(['de-DE', 'en-US', 'es-ES'])('shows truthful state and scope in %s without exposing tokens', async locale => {
    mocks.locale = locale; const text = catalogs[locale].auth.sessions;
    mocks.get.mockResolvedValue(envelope([row({ current_refresh_hash: 'PRIVATE-REFRESH-HASH', token: 'RAW-SECRET' }),
      row({ id: 'past', current: false, status: 'revoked', revoked_at: '2026-10-01T12:00:00+00:00', revoke_reason: 'refresh_reuse' }),
      row({ id: 'expired', current: false, status: 'expired' })]));
    const { container } = render(<SessionsSection />);
    await screen.findByText(text.reuseReason);
    expect(screen.getByRole('heading', { name: text.title })).toBeVisible();
    expect(container).toHaveTextContent(text.transitionHint); expect(container).toHaveTextContent(text.deviceHint);
    expect(container.textContent).not.toMatch(/auth\.sessions\.|PRIVATE-REFRESH-HASH|RAW-SECRET/);
    expect(screen.getAllByRole('button', { name: new RegExp(text.revokeCurrent) })).toHaveLength(1);
    expect(screen.queryByRole('button', { name: text.revokeOther, exact: true })).not.toBeInTheDocument();
    expect(Object.keys(text)).toEqual(Object.keys(labels));
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it.each([401, 500])('keeps HTTP %s loading errors visible and permits an explicit retry', async status => {
    mocks.get.mockRejectedValueOnce(new Error(`HTTP ${status}: Synthetic database unavailable`));
    render(<SessionsSection />);
    expect(await screen.findByRole('alert')).toHaveTextContent(`HTTP ${status}`);
    expect(mocks.post).not.toHaveBeenCalled(); expect(mocks.logout).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: labels.retry }));
    await screen.findByRole('heading', { name: 'Firefox / Linux' });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('does not mutate when explicit confirmation is cancelled', async () => {
    mocks.confirm.mockResolvedValue(false);
    render(<SessionsSection />);
    fireEvent.click(await screen.findByRole('button', { name: labels.revokeOther, exact: true }));
    await waitFor(() => expect(mocks.confirm).toHaveBeenCalledWith(labels.confirmOther));
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('allows readonly own revocation and suppresses duplicate clicks through pending confirmation and request', async () => {
    const confirmation = deferred(); const request = deferred();
    mocks.confirm.mockReturnValue(confirmation.promise); mocks.post.mockReturnValue(request.promise);
    render(<SessionsSection />);
    const button = await screen.findByRole('button', { name: labels.revokeOther, exact: true });
    fireEvent.click(button); fireEvent.click(button);
    expect(mocks.confirm).toHaveBeenCalledOnce(); expect(button).toBeDisabled();
    await act(async () => confirmation.resolve(true));
    expect(mocks.post).toHaveBeenCalledOnce();
    expect(mocks.post).toHaveBeenCalledWith('/auth/sessions/other/revoke', { confirmed: true }, expect.objectContaining({ signal: expect.any(AbortSignal) }));
    fireEvent.click(button);
    await act(async () => request.resolve(row({ id: 'other', current: false, status: 'revoked', revoked_at: '2026-10-01T12:00:00Z' })));
    expect(await screen.findByText(labels.revokedSuccess)).toBeVisible();
    expect(mocks.post).toHaveBeenCalledOnce(); expect(mocks.logout).not.toHaveBeenCalled();
  });

  it('requires a real revocation receipt before clearing the current login', async () => {
    mocks.post.mockResolvedValueOnce({ detail: 'OK' });
    render(<SessionsSection />);
    fireEvent.click(await screen.findByRole('button', { name: labels.revokeCurrent }));
    expect(await screen.findByRole('alert')).toHaveTextContent(labels.invalidResponse);
    expect(mocks.logout).not.toHaveBeenCalled(); expect(mocks.clearUser).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByRole('alert')).toHaveFocus());
    fireEvent.click(screen.getByRole('button', { name: labels.revokeCurrent }));
    await waitFor(() => expect(mocks.logout).toHaveBeenCalledOnce());
    expect(mocks.clearUser).toHaveBeenCalledOnce(); expect(mocks.confirm).toHaveBeenLastCalledWith(labels.confirmCurrent);
  });

  it('preserves active state and server details on failed revocation', async () => {
    mocks.post.mockRejectedValue(new Error('HTTP 503: Synthetic auth database unavailable'));
    render(<SessionsSection />);
    fireEvent.click(await screen.findByRole('button', { name: labels.revokeOther, exact: true }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Synthetic auth database unavailable');
    expect(screen.getByRole('button', { name: labels.revokeOther, exact: true })).toBeEnabled();
    expect(screen.queryByText(labels.revokedSuccess)).not.toBeInTheDocument(); expect(mocks.logout).not.toHaveBeenCalled();
  });

  it('paginates all journal entries and distinguishes the legacy nonpersistent mode', async () => {
    mocks.get.mockResolvedValueOnce(envelope(Array.from({ length: 20 }, (_, id) => row({ id: `page-${id}`, current: false })), { total: 21 }))
      .mockResolvedValueOnce(envelope([row({ id: 'last', current: false, device_label: 'Safari / iOS' })], { total: 21, offset: 20, current_session_id: null, legacy_current: true, persistent: false }));
    render(<SessionsSection />);
    await waitFor(() => expect(screen.getByRole('button', { name: labels.next })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: labels.next }));
    await screen.findByRole('heading', { name: 'Safari / iOS' });
    expect(mocks.get).toHaveBeenLastCalledWith('/auth/sessions?offset=20&limit=20', expect.any(Object));
    expect(screen.getByText(labels.legacyCurrent)).toBeVisible(); expect(screen.getByText(labels.memoryHint)).toBeVisible();
    expect(screen.getByText('21–21 von 21 erfassten Sitzungen')).toBeVisible();
    expect(screen.getByRole('button', { name: labels.next })).toBeDisabled();
  });

  it('does not send an old account command after the account changes during confirmation', async () => {
    const confirmation = deferred(); mocks.confirm.mockReturnValue(confirmation.promise);
    const nextLoad = deferred();
    mocks.get.mockResolvedValueOnce(envelope([row(), other()])).mockReturnValueOnce(nextLoad.promise);
    const view = render(<SessionsSection />);
    fireEvent.click(await screen.findByRole('button', { name: labels.revokeOther, exact: true }));
    mocks.auth = { ...mocks.auth, user: { id: 'new-account', role: 'readonly' } };
    view.rerender(<SessionsSection />);
    expect(screen.queryByRole('heading', { name: 'Firefox / Linux' })).not.toBeInTheDocument();
    expect(screen.getByText(labels.loading)).toBeVisible();
    await act(async () => confirmation.resolve(true));
    expect(mocks.post).not.toHaveBeenCalled();
    await act(async () => nextLoad.resolve(envelope([row({ device_label: 'Safari / iOS' })])));
    expect(screen.getByRole('heading', { name: 'Safari / iOS' })).toBeVisible();
  });

  it.each([
    envelope([row()], { total: 0 }),
    envelope([row()], { current_session_id: null }),
    envelope([row(), row()]),
    envelope([row({ status: 'revoked', revoked_at: null })]),
  ])('rejects inconsistent session evidence before offering a write action', async invalid => {
    mocks.get.mockResolvedValue(invalid);
    render(<SessionsSection />);
    expect(await screen.findByRole('alert')).toHaveTextContent(labels.invalidResponse);
    expect(screen.queryByRole('button', { name: labels.revokeCurrent })).not.toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled(); expect(mocks.logout).not.toHaveBeenCalled();
  });

  it('aborts the pending load when the panel is closed', () => {
    mocks.get.mockReturnValue(new Promise(() => {}));
    const view = render(<SessionsSection />);
    const signal = mocks.get.mock.calls[0][1].signal;
    view.unmount(); expect(signal.aborted).toBe(true);
  });

  it('mounts the security panel only on explicit tab selection for readonly users', async () => {
    render(<Settings />);
    expect(mocks.get).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: labels.tab }));
    const region = await screen.findByRole('region', { name: labels.title });
    await screen.findByRole('heading', { name: 'Edge / Windows' });
    expect(within(region).getByRole('heading', { name: 'Edge / Windows' })).toBeVisible();
    expect(mocks.get).toHaveBeenCalledOnce();
  });
});
