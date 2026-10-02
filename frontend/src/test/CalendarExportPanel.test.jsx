import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import CalendarExportPanel from '../components/CalendarExportPanel';
import de from '../../../i18n/de-DE.json';
import en from '../../../i18n/en-US.json';
import es from '../../../i18n/es-ES.json';

const mocks = vi.hoisted(() => ({ get: vi.fn(), getBlob: vi.fn(), auth: null, locale: 'de-DE', t: null }));
vi.mock('../api', () => ({ api: { get: mocks.get, getBlob: mocks.getBlob } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => mocks.auth }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: mocks.t }) }));
const catalogs = { 'de-DE': de, 'en-US': en, 'es-ES': es };
const text = de.pages.calendar.export;
const portfolios = [
  { id: 'portfolio A&?', name: 'Nord & Süd', timezone: 'Europe/Berlin' },
  { id: 'portfolio-B', name: 'West', timezone: 'Europe/London' },
];
const calendar = () => new Blob(['BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:Synthetic\r\nEND:VCALENDAR\r\n'], { type: 'text/calendar;charset=utf-8' });
const deferred = () => { let resolve; let reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
let click;
let createUrl;
let revokeUrl;
const selectPortfolio = async (id = portfolios[0].id) => {
  await screen.findByRole('option', { name: /Nord & Süd/ });
  fireEvent.change(screen.getByRole('combobox', { name: text.portfolio }), { target: { value: id } });
};

beforeEach(() => {
  mocks.get.mockReset().mockResolvedValue(portfolios); mocks.getBlob.mockReset().mockResolvedValue(calendar());
  mocks.auth = { user: { id: 'synthetic-reader', role: 'readonly', portfolio_access: 'all', is_active: true } };
  mocks.locale = 'de-DE';
  mocks.t = (key, parameters = {}) => {
    let value = key.split('.').reduce((node, part) => node?.[part], catalogs[mocks.locale]) || key;
    for (const [name, replacement] of Object.entries(parameters)) value = value.replaceAll(`{{${name}}}`, String(replacement));
    return value;
  };
  createUrl = vi.fn(() => 'blob:synthetic-calendar'); revokeUrl = vi.fn();
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: createUrl, revokeObjectURL: revokeUrl }));
  click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('explicit portfolio calendar download', () => {
  it.each(['de-DE', 'en-US', 'es-ES'])('allows readonly download only after selection in %s', async locale => {
    mocks.locale = locale;
    const labels = catalogs[locale].pages.calendar.export;
    const { container, unmount } = render(<CalendarExportPanel />);
    await screen.findByRole('option', { name: /Nord & Süd/ });
    expect(screen.getByRole('button', { name: labels.download })).toBeDisabled();
    expect(mocks.getBlob).not.toHaveBeenCalled();
    expect(container).toHaveTextContent(labels.hint);
    expect(container.textContent).not.toContain('pages.calendar.export.');
    fireEvent.change(screen.getByRole('combobox', { name: labels.portfolio }), { target: { value: portfolios[0].id } });
    fireEvent.click(screen.getByRole('button', { name: labels.download }));
    await waitFor(() => expect(click).toHaveBeenCalledOnce());
    expect(mocks.getBlob).toHaveBeenCalledWith('/calendar/export.ics?portfolio_id=portfolio%20A%26%3F', { signal: expect.any(AbortSignal) });
    expect(createUrl).toHaveBeenCalledWith(expect.any(Blob));
    const link = click.mock.instances[0];
    expect(link.download).toBe('immomanager-calendar.ics'); expect(link.href).toBe('blob:synthetic-calendar');
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Nord & Süd'));
    unmount(); expect(revokeUrl).toHaveBeenCalledWith('blob:synthetic-calendar');
    expect(Object.keys(labels)).toEqual(Object.keys(text));
  });

  it.each([401, 403, 404, 422, 500])('shows server HTTP %s details without a successful download, retaining the choice', async status => {
    mocks.getBlob.mockRejectedValueOnce(Object.assign(new Error(`HTTP ${status}: Uhrzeit bitte korrigieren`), { statusCode: status }));
    render(<CalendarExportPanel />); await selectPortfolio();
    fireEvent.click(screen.getByRole('button', { name: text.download }));
    expect(await screen.findByRole('alert')).toHaveTextContent(`HTTP ${status}: Uhrzeit bitte korrigieren`);
    expect(createUrl).not.toHaveBeenCalled(); expect(click).not.toHaveBeenCalled();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(screen.getByRole('combobox')).toHaveValue(portfolios[0].id);
    fireEvent.click(screen.getByRole('button', { name: text.download }));
    await waitFor(() => expect(click).toHaveBeenCalledOnce());
  });

  it.each([
    new Blob(['<html>Login</html>'], { type: 'text/html' }),
    new Blob(['{"access_token":"do-not-download"}'], { type: 'application/json' }),
    new Blob(['BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:Synthetic\r\n'], { type: 'text/calendar' }),
    new Blob(['BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:Synthetic\r\nEND:VCALENDAR\r\n<html>'], { type: 'text/calendar' }),
    null,
  ])('rejects malformed or error content before allocating a download URL (%#)', async blob => {
    mocks.getBlob.mockResolvedValue(blob);
    render(<CalendarExportPanel />); await selectPortfolio();
    fireEvent.click(screen.getByRole('button', { name: text.download }));
    expect(await screen.findByRole('alert')).toHaveTextContent(text.invalidCalendar);
    expect(createUrl).not.toHaveBeenCalled(); expect(click).not.toHaveBeenCalled();
  });

  it('suppresses double clicks and aborts a stale response when the portfolio changes', async () => {
    const pending = deferred(); mocks.getBlob.mockReturnValue(pending.promise);
    render(<CalendarExportPanel />); await selectPortfolio();
    const button = screen.getByRole('button', { name: text.download });
    fireEvent.click(button); fireEvent.click(button);
    expect(mocks.getBlob).toHaveBeenCalledOnce(); expect(button).toBeDisabled();
    expect(screen.getByRole('combobox')).toBeEnabled();
    const signal = mocks.getBlob.mock.calls[0][1].signal;
    fireEvent.change(screen.getByRole('combobox'), { target: { value: portfolios[1].id } });
    expect(signal.aborted).toBe(true);
    await act(async () => pending.resolve(calendar()));
    expect(click).not.toHaveBeenCalled(); expect(screen.queryByRole('status')).not.toBeInTheDocument();
    mocks.getBlob.mockResolvedValue(calendar());
    fireEvent.click(screen.getByRole('button', { name: text.download }));
    await waitFor(() => expect(click).toHaveBeenCalledOnce());
    expect(mocks.getBlob.mock.calls[1][0]).toContain('portfolio-B');
  });

  it.each(['user', 'grants', 'unmount'])('aborts pending work after %s changes with no stale download', async change => {
    const pending = deferred(); mocks.getBlob.mockReturnValue(pending.promise);
    const view = render(<CalendarExportPanel />); await selectPortfolio();
    fireEvent.click(screen.getByRole('button', { name: text.download }));
    const signal = mocks.getBlob.mock.calls[0][1].signal;
    if (change === 'unmount') view.unmount();
    else {
      mocks.auth = { user: { ...mocks.auth.user, ...(change === 'user' ? { id: 'other-reader' } : { portfolio_access: 'selected', portfolio_ids: ['portfolio-B'] }) } };
      view.rerender(<CalendarExportPanel />);
    }
    expect(signal.aborted).toBe(true);
    await act(async () => pending.resolve(calendar()));
    expect(click).not.toHaveBeenCalled(); expect(createUrl).not.toHaveBeenCalled();
    if (change !== 'unmount') expect(screen.getByRole('combobox')).toHaveValue('');
  });

  it('loads bounded portfolio pages and clears a former selection on paging', async () => {
    const pageOne = Array.from({ length: 51 }, (_, index) => ({ id: `id-${index}`, name: `Portfolio ${index}`, timezone: 'UTC' }));
    mocks.get.mockResolvedValueOnce(pageOne).mockResolvedValueOnce(portfolios);
    render(<CalendarExportPanel />);
    await screen.findByRole('option', { name: 'Portfolio 0 · UTC' });
    expect(screen.queryByRole('option', { name: 'Portfolio 50 · UTC' })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'id-0' } });
    fireEvent.click(screen.getByRole('button', { name: text.next }));
    await screen.findByRole('option', { name: /Nord & Süd/ });
    expect(mocks.get.mock.calls[1][0]).toBe('/portfolios?skip=50&limit=51&sort_by=id');
    expect(screen.getByRole('combobox')).toHaveValue('');
    expect(screen.getByRole('button', { name: text.download })).toBeDisabled();
    expect(screen.getByRole('button', { name: text.previous })).toBeEnabled();
  });

  it('retries an invalid portfolio response explicitly without exporting', async () => {
    mocks.get.mockResolvedValueOnce([{ id: 'bad', name: 'Bad', timezone: null }]);
    render(<CalendarExportPanel />);
    expect(await screen.findByRole('alert')).toHaveTextContent(text.invalidPortfolios);
    fireEvent.click(screen.getByRole('button', { name: text.retry }));
    await screen.findByRole('option', { name: /Nord & Süd/ });
    expect(mocks.getBlob).not.toHaveBeenCalled();
  });

  it('does not load or render for an anonymous actor', () => {
    mocks.auth = null;
    const { container } = render(<CalendarExportPanel />);
    expect(container).toBeEmptyDOMElement(); expect(mocks.get).not.toHaveBeenCalled();
  });
});
