import { act, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Calendar from '../pages/Calendar';
import de from '../../../i18n/de-DE.json';

const mocks = vi.hoisted(() => ({ auth: null, get: vi.fn(), getAll: vi.fn(), getBlob: vi.fn(), confirm: vi.fn() }));
vi.mock('../api', () => ({ api: { get: mocks.get, getAll: mocks.getAll, getBlob: mocks.getBlob } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => mocks.auth }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: (key, args = {}) => {
  let value = key.split('.').reduce((node, part) => node?.[part], de) || key;
  for (const [name, text] of Object.entries(args)) value = value.replaceAll(`{{${name}}}`, String(text));
  return value;
} }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => mocks.confirm }));
const event = title => ({ id: title, title, event_type: 'deadline', event_date: '2026-10-05', event_time: null, location: 'Berlin', participants: null });
const user = role => ({ user: { id: `synthetic-${role}`, role, portfolio_access: 'selected', portfolio_ids: ['allowed'] } });
const deferred = () => { let resolve; const promise = new Promise(yes => { resolve = yes; }); return { promise, resolve }; };

beforeEach(() => {
  mocks.auth = user('readonly'); mocks.get.mockReset(); mocks.getAll.mockReset();
  mocks.get.mockImplementation(path => {
    if (path === '/calendar/schedules' || path === '/tasks/operational-status') return Promise.reject(new Error('HTTP403: Scheduler-Verwaltung nicht erlaubt'));
    if (path.startsWith('/portfolios?')) return Promise.resolve([{ id: 'allowed', name: 'Eigenes Portfolio', timezone: 'Europe/Berlin' }]);
    throw new Error(`Unexpected request ${path}`);
  });
  mocks.getAll.mockImplementation(path => Promise.resolve(path === '/calendar' ? [event('Sichtbarer Bestandstermin')] : []));
});

describe('calendar reading remains independent from scheduler administration', () => {
  it('shows actual readonly event rows without requesting denied scheduler endpoints or inventing an empty schedule', async () => {
    render(<Calendar />);
    expect(await screen.findByRole('row', { name: /Sichtbarer Bestandstermin/ })).toBeVisible();
    expect(screen.queryByRole('columnheader', { name: /Wiederholung/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: de.operational.run })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: de.operational.title })).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(mocks.get.mock.calls.some(([path]) => path === '/calendar/schedules' || path === '/tasks/operational-status')).toBe(false);
    expect(await screen.findByRole('option', { name: 'Eigenes Portfolio · Europe/Berlin' })).toBeInTheDocument();
  });

  it('aborts the old shared read on an actor/role change and never publishes its late rows', async () => {
    mocks.auth = user('eigentuemer');
    const pending = deferred();
    mocks.get.mockImplementation(path => Promise.resolve(path.startsWith('/portfolios?')
      ? [{ id: 'allowed', name: 'Eigenes Portfolio', timezone: 'Europe/Berlin' }] : path === '/calendar/schedules' ? [] : {}));
    mocks.getAll.mockImplementation(path => path === '/calendar' ? pending.promise : Promise.resolve([]));
    const view = render(<Calendar />);
    const oldSignal = mocks.getAll.mock.calls[0][1].signal;
    expect(screen.getByRole('heading', { name: de.pages.calendar.export.title })).toBeVisible();
    mocks.auth = user('readonly');
    mocks.getAll.mockImplementation(path => Promise.resolve(path === '/calendar' ? [event('Neuer lesender Termin')] : []));
    view.rerender(<Calendar />);
    expect(oldSignal.aborted).toBe(true);
    expect(await screen.findByRole('row', { name: /Neuer lesender Termin/ })).toBeVisible();
    await act(async () => pending.resolve([event('Alter fremder Termin')]));
    expect(screen.queryByText('Alter fremder Termin')).not.toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: /Wiederholung/ })).not.toBeInTheDocument();
  });

  it('keeps the explicit export selection accessible when event loading fails', async () => {
    mocks.getAll.mockRejectedValue(new Error('Termine vorübergehend nicht lesbar'));
    render(<Calendar />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Termine vorübergehend nicht lesbar');
    await waitFor(() => expect(screen.getByRole('combobox', { name: de.pages.calendar.export.portfolio })).toBeEnabled());
    expect(screen.getByRole('option', { name: 'Eigenes Portfolio · Europe/Berlin' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: de.pages.calendar.export.title })).toBeVisible();
    expect(mocks.getBlob).not.toHaveBeenCalled();
  });
});
