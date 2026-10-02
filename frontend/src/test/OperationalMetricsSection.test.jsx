import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import OperationalMetricsSection from '../pages/settings/OperationalMetricsSection';
import Settings from '../pages/Settings';
import de from '../../../i18n/de-DE.json';
import en from '../../../i18n/en-US.json';
import es from '../../../i18n/es-ES.json';

const mocks = vi.hoisted(() => ({ get: vi.fn(), locale: 'de-DE', auth: null, t: null }));
vi.mock('../api', () => ({ api: { get: mocks.get } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: mocks.t, locale: mocks.locale }) }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => mocks.auth }));
vi.mock('../contexts/PreferencesContext', () => ({ usePreferences: () => ({ prefs: {} }) }));
vi.mock('../contexts/DevModeContext', () => ({ useDevMode: () => ({ enabled: false }) }));
vi.mock('../pages/settings/TwoFactorSection', () => ({ default: () => null }));
vi.mock('../pages/settings/SessionsSection', () => ({ default: () => null }));
vi.mock('../pages/settings/UserManagementSection', () => ({ default: () => null }));
vi.mock('../pages/settings/BackupSection', () => ({ default: () => null }));
vi.mock('../pages/settings/UpdateSection', () => ({ default: () => null }));
vi.mock('../pages/settings/AutotestSection', () => ({ default: () => null }));

const catalogs = { 'de-DE': de, 'en-US': en, 'es-ES': es };
const labels = de.settings.operations;
const translated = key => key.split('.').reduce((value, part) => value?.[part], catalogs[mocks.locale]) || key;
const aggregate = (count = 0, total_ms = 0) => ({ count, total_ms });
const payload = () => ({ scope: 'process_worker', persistent: false, started_at: '2026-10-01T10:00:00+00:00', uptime_seconds: 90000,
  process: { cpu_seconds: 12.5 }, database: { state: 'connected', backend: 'sqlite', persistent: true, duration_ms: 2.1, check: 'connectivity_only' },
  requests: { completed: 15, inflight: 1, peak_inflight: 3, exceptions: 1, aborted: 2, series: [
    { group: 'finance', method: 'GET', outcome: 'success', ...aggregate(12, 1200) },
    { group: 'finance', method: 'POST', outcome: 'server_error', ...aggregate(1, 200) },
    { group: 'files', method: 'GET', outcome: 'aborted', ...aggregate(2, 10000) },
  ] }, jobs: { operational_tick: { success: aggregate(4, 100), error: aggregate(1, 10) } },
  scheduler: { automatic_enabled: false, automatic_running: false } });
const deferred = () => { let resolve; let reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const owner = () => ({ isAdmin: true, role: 'eigentuemer', user: { id: 'synthetic-owner', role: 'eigentuemer', portfolio_access: 'all' } });

beforeEach(() => {
  mocks.auth = owner(); mocks.locale = 'de-DE'; mocks.t = translated;
  mocks.get.mockReset().mockResolvedValue(payload());
});

describe('installation operator status', () => {
  it.each(['de-DE', 'en-US', 'es-ES'])('shows real scope, database and weighted durations in %s', async locale => {
    mocks.locale = locale;
    const text = catalogs[locale].settings.operations;
    const value = payload(); value.token = 'UNEXPECTED-SECRET'; value.user_id = 'PRIVATE-USER';
    mocks.get.mockResolvedValue(value);
    const { container } = render(<OperationalMetricsSection />);
    await screen.findByText(text.database.connected);
    expect(screen.getByRole('heading', { name: text.title })).toBeVisible();
    expect(container).toHaveTextContent(text.scopeHint);
    expect(container).toHaveTextContent(text.connectivityHint);
    expect(container).toHaveTextContent(text.jobHint);
    expect(container).toHaveTextContent(text.schedulerDisabled);
    const row = screen.getByRole('row', { name: new RegExp(text.groups.finance) });
    const cells = within(row).getAllByRole('cell');
    expect(cells[0]).toHaveTextContent('13'); expect(cells[1]).toHaveTextContent('1');
    expect(cells[2]).toHaveTextContent(new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(1400 / 13));
    expect(container.textContent).not.toMatch(/settings\.operations\.|UNEXPECTED-SECRET|PRIVATE-USER/);
    expect(Object.keys(text)).toEqual(Object.keys(labels));
    expect(mocks.get).toHaveBeenCalledOnce();
    expect(mocks.get).toHaveBeenCalledWith('/admin/operational-metrics', { signal: expect.any(AbortSignal) });
  });

  it.each(['readonly', 'buchhaltung', 'techniker', 'dienstleister', 'selected', 'anonymous'])('does not request installation metrics for %s', async role => {
    mocks.auth = role === 'anonymous' ? null : { role: role === 'selected' ? 'verwalter' : role,
      user: { id: 'scoped', portfolio_access: role === 'selected' ? 'selected' : 'all' } };
    const { container } = render(<OperationalMetricsSection />);
    expect(container).toBeEmptyDOMElement();
    expect(mocks.get).not.toHaveBeenCalled();
  });

  it.each([401, 403, 500])('HTTP %s is visible with no false healthy status and can be retried explicitly', async code => {
    mocks.get.mockRejectedValueOnce(new Error(`HTTP ${code}: Synthetic connection error`));
    render(<OperationalMetricsSection />);
    expect(await screen.findByRole('alert')).toHaveTextContent(`HTTP ${code}`);
    expect(screen.queryByText(labels.database.connected)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: labels.refresh }));
    await screen.findByText(labels.database.connected);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it.each([
    value => { value.scope = 'all_workers'; },
    value => { value.database.state = 'healthy'; },
    value => { value.database.persistent = 'false'; },
    value => { value.requests.series[0].group = 'PRIVATE-EMAIL@example.test'; },
    value => { value.requests.series[0].total_ms = Infinity; },
    value => { value.requests.completed = 16; },
    value => { delete value.jobs; },
  ])('rejects an invalid response rather than asserting success (%#)', async corrupt => {
    const value = payload(); corrupt(value); mocks.get.mockResolvedValue(value);
    render(<OperationalMetricsSection />);
    expect(await screen.findByRole('alert')).toHaveTextContent(labels.invalidResponse);
    expect(screen.queryByText(labels.database.connected)).not.toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('preserves the distinction between unavailable SQL and volatile memory', async () => {
    const value = payload(); value.database.state = 'unavailable';
    mocks.get.mockResolvedValue(value);
    render(<OperationalMetricsSection />);
    await screen.findByText(labels.database.unavailable);
    expect(screen.getByRole('status')).toHaveTextContent(labels.database.unavailable);
    expect(screen.queryByText(labels.memoryHint)).not.toBeInTheDocument();
    value.database = { ...value.database, state: 'not_configured', backend: 'memory', persistent: false };
    fireEvent.click(screen.getByRole('button', { name: labels.refresh }));
    await screen.findByText(labels.memoryHint);
    expect(screen.getByRole('status')).toHaveTextContent(labels.database.not_configured);
  });

  it('suppresses duplicate refreshes and clears a previously healthy result on failure', async () => {
    render(<OperationalMetricsSection />);
    await screen.findByText(labels.database.connected);
    const request = deferred(); mocks.get.mockReturnValue(request.promise);
    const refresh = screen.getByRole('button', { name: labels.refresh });
    fireEvent.click(refresh); fireEvent.click(refresh);
    expect(mocks.get).toHaveBeenCalledTimes(2); expect(refresh).toBeDisabled();
    expect(screen.queryByText(labels.database.connected)).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent(labels.loading);
    await act(async () => request.reject(new Error('HTTP 403: Rights changed')));
    expect(await screen.findByRole('alert')).toHaveTextContent('HTTP 403');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(refresh).toBeEnabled();
  });

  it('aborts on permission loss and cannot publish a late old-account result', async () => {
    const request = deferred(); mocks.get.mockReturnValue(request.promise);
    const { rerender, container } = render(<OperationalMetricsSection />);
    const signal = mocks.get.mock.calls[0][1].signal;
    mocks.auth = { role: 'verwalter', user: { id: 'synthetic-owner', portfolio_access: 'selected' } };
    rerender(<OperationalMetricsSection />);
    expect(signal.aborted).toBe(true); expect(container).toBeEmptyDOMElement();
    await act(async () => request.resolve(payload()));
    expect(container).toBeEmptyDOMElement(); expect(mocks.get).toHaveBeenCalledOnce();
  });

  it('aborts the probe on unmount and never starts automatic polling', async () => {
    const request = deferred(); mocks.get.mockReturnValue(request.promise);
    const { unmount } = render(<OperationalMetricsSection />);
    const signal = mocks.get.mock.calls[0][1].signal;
    unmount(); expect(signal.aborted).toBe(true);
    await act(async () => request.resolve(payload()));
    expect(mocks.get).toHaveBeenCalledOnce();
  });

  it('is reachable in the existing System settings only for installation administrators', async () => {
    mocks.get.mockImplementation(path => Promise.resolve(path === '/admin/version' ? { version: '1.0.0' } : payload()));
    const { rerender } = render(<Settings />);
    expect(screen.queryByRole('heading', { name: labels.title })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: de.userManagement.settingsTabs.system }));
    await screen.findByRole('heading', { name: labels.title });
    await waitFor(() => expect(mocks.get).toHaveBeenCalledWith('/admin/operational-metrics', expect.any(Object)));
    mocks.auth = { isAdmin: false, role: 'readonly', user: { id: 'viewer', portfolio_access: 'all' } };
    rerender(<Settings />);
    expect(screen.queryByRole('heading', { name: labels.title })).not.toBeInTheDocument();
  });
});
