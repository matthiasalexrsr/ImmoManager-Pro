import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import OperationalMetricsSection from '../pages/settings/OperationalMetricsSection';
import de from '../../../i18n/de-DE.json';
import en from '../../../i18n/en-US.json';
import es from '../../../i18n/es-ES.json';

const mocks = vi.hoisted(() => ({ get: vi.fn(), locale: 'de-DE', t: null }));
vi.mock('../api', () => ({ api: { get: mocks.get } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: mocks.t, locale: mocks.locale }) }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ role: 'eigentuemer', user: { id: 'review-owner', portfolio_access: 'all' } }) }));

const catalogs = { 'de-DE': de, 'en-US': en, 'es-ES': es };
const translate = key => key.split('.').reduce((value, part) => value?.[part], catalogs[mocks.locale]) || key;
const aggregate = () => ({ count: 0, total_ms: 0 });
const payload = () => ({ scope: 'process_worker', persistent: false, started_at: '2026-10-01T10:00:00Z', uptime_seconds: 60,
  process: { cpu_seconds: 0.1 }, database: { state: 'connected', backend: 'sqlite', persistent: true, duration_ms: 1, check: 'connectivity_only' },
  requests: { completed: 0, inflight: 1, peak_inflight: 1, exceptions: 0, aborted: 0, series: [] },
  jobs: { operational_tick: { success: aggregate(), error: aggregate() } },
  scheduler: { automatic_enabled: false, automatic_running: false } });

beforeEach(() => {
  mocks.locale = 'de-DE'; mocks.t = translate;
  mocks.get.mockReset().mockImplementation(() => Promise.resolve(payload()));
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

it.each(['de-DE', 'en-US', 'es-ES'])('shows reachable volatile SQL honestly in %s', async locale => {
  mocks.locale = locale;
  const value = payload(); value.database.persistent = false;
  mocks.get.mockResolvedValue(value);
  render(<OperationalMetricsSection />);
  const labels = catalogs[locale].settings.operations;
  expect(await screen.findByText(labels.database.connected)).toBeVisible();
  expect(screen.getByRole('status')).toHaveTextContent(labels.memoryHint);
  expect(screen.getByText(labels.connectivityHint)).toBeVisible();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('stays mounted for a day without polling or refetching on focus and requires explicit refresh', async () => {
  vi.useFakeTimers();
  let view;
  await act(async () => { view = render(<OperationalMetricsSection />); });
  expect(mocks.get).toHaveBeenCalledOnce();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(24 * 60 * 60 * 1000);
    fireEvent.focus(window);
    fireEvent(document, new Event('visibilitychange'));
    view.rerender(<OperationalMetricsSection />);
  });
  expect(mocks.get).toHaveBeenCalledOnce();
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: de.settings.operations.refresh })); });
  expect(mocks.get).toHaveBeenCalledTimes(2);
  expect(screen.getByText(de.settings.operations.database.connected)).toBeVisible();
});
