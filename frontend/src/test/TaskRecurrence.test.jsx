import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import Tasks from '../pages/Tasks';
import { api } from '../api';
import { workspace } from '../utils/workspaceClient';
import { recurrenceConfig, recurrenceError, recurrencePreset, recurrenceRule, recurrenceSummary } from '../features/tasks/taskRecurrence';
import german from '../../../i18n/de-DE.json';
import english from '../../../i18n/en-US.json';
import spanish from '../../../i18n/es-ES.json';

const state = vi.hoisted(() => ({ tasks: [], drafts: [], auth: null, locale: 'de-DE', lookups: { properties: [], units: [] },
  toast: { success: vi.fn(), error: vi.fn() }, store: { invalidateRelated: vi.fn() } }));
const translations = { 'de-DE': german, 'en-US': english, 'es-ES': spanish };
function translate(key, params = {}) {
  let value = key.split('.').reduce((obj, part) => obj?.[part], translations[state.locale]) || key;
  for (const [name, replacement] of Object.entries(params)) value = value.replace(`{{${name}}}`, replacement);
  return value;
}
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: translate, locale: state.locale }) }));
vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), patch: vi.fn() } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => state.auth, useCanWrite: () => true }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => state.store,
  useEntities: key => ({ items: state.lookups[key], loading: false, error: null }) }));
vi.mock('../components/Toast', () => ({ useToast: () => state.toast }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => vi.fn() }));
vi.mock('../components/DataTable', () => ({ default: ({ data, onAdd, onEdit }) => <div>
  <button onClick={() => onAdd()}>Neue Aufgabe</button>
  {data.map(row => <button key={row.id} onClick={() => onEdit(row)}>{row.title} bearbeiten</button>)}
</div> }));
vi.mock('../utils/workspaceClient', async original => ({ ...await original(), workspace: {
  list: vi.fn(), put: vi.fn(), remove: vi.fn(), get: vi.fn(), rebase: vi.fn(), command: () => crypto.randomUUID(),
} }));

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  state.tasks = []; state.drafts = []; state.auth = null; state.locale = 'de-DE';
  api.list.mockImplementation(async () => state.tasks);
  api.post.mockImplementation(async (_url, data) => ({ ...data, id: 'created' }));
  api.patch.mockImplementation(async (_url, data) => ({ ...state.tasks[0], ...data }));
  workspace.list.mockImplementation(async () => ({ items: state.drafts, next_cursor: null }));
  workspace.put.mockImplementation(async (_resource, id, body) => {
    const row = { ...body, id, revision: body.base_revision + 1, source_state: { status: 'current' } };
    state.drafts = [row]; return row;
  });
  workspace.remove.mockResolvedValue(undefined);
});
afterEach(cleanup);

const renderTasks = () => render(<MemoryRouter initialEntries={['/tasks']}><Tasks /></MemoryRouter>);
const change = (label, value) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
async function newTask() {
  const rendered = renderTasks();
  fireEvent.click(await screen.findByRole('button', { name: 'Neue Aufgabe' }));
  await waitFor(() => expect(screen.getByLabelText('Wiederholung')).toBeEnabled());
  return rendered;
}
const submit = () => fireEvent.submit(screen.getByRole('dialog').querySelector('form'));

describe('supported recurrence dialect', () => {
  it.each([
    ['daily', 'DAILY', '1'], ['weekly', 'WEEKLY', '1'], ['monthly', 'MONTHLY', '1'],
    ['quarterly', 'MONTHLY', '3'], ['halfYearly', 'MONTHLY', '6'], ['yearly', 'YEARLY', '1'],
  ])('maps the %s preset without changing its frequency or interval', (preset, frequency, interval) => {
    const rule = recurrenceRule({ frequency, interval, end: 'never' });
    expect(recurrencePreset(rule)).toBe(preset);
    expect(recurrenceError(rule)).toBeNull();
  });

  it('decodes both limits and unfinished fields without changing the original text', () => {
    const rule = ' count=003 ; freq=monthly ; until=2028-02-29 ; interval=02 ';
    expect(recurrenceConfig(rule)).toEqual({ frequency: 'MONTHLY', interval: '02', count: '003', until: '2028-02-29', end: 'both' });
    expect(recurrenceError(rule)).toBeNull();
    const unfinished = recurrenceRule({ ...recurrenceConfig(rule), interval: '', until: '' });
    expect(recurrenceConfig(unfinished)).toMatchObject({ interval: '', until: '', end: 'both' });
    expect(recurrenceError(unfinished)).toBe('invalidInterval');
  });

  it.each([
    ['FREQ=DAILY;BYDAY=MO', 'invalidRule'], ['FREQ=DAILY;FREQ=WEEKLY', 'invalidRule'],
    ['FREQ=HOURLY', 'invalidRule'], ['FREQ=DAILY;INTERVAL=1.5', 'invalidInterval'],
    ['FREQ=DAILY;INTERVAL=0', 'invalidInterval'], ['FREQ=DAILY;COUNT=-1', 'invalidCount'],
    ['FREQ=DAILY;COUNT=', 'invalidCount'], ['FREQ=MONTHLY;UNTIL=2027-02-29', 'invalidUntil'],
    ['FREQ=YEARLY;UNTIL=0000-01-01', 'invalidUntil'], ['FREQ=DAILY;UNTIL=2025-W53', 'invalidUntil'],
  ])('rejects %s before saving', (rule, error) => expect(recurrenceError(rule)).toBe(error));

  it.each(['2028-02-29', '20280229', '2026-W40-4', '2026W404', '2026-W40', '2026W40'])('retains the supported backend date spelling %s', until => {
    expect(recurrenceError(`FREQ=DAILY;UNTIL=${until}`)).toBeNull();
  });

  it('distinguishes quarterly and bounded recurrences in the list summary', () => {
    expect(recurrenceSummary('FREQ=MONTHLY;INTERVAL=3', translate)).toBe('Vierteljährlich');
    expect(recurrenceSummary('FREQ=WEEKLY;INTERVAL=2;COUNT=3;UNTIL=2027-05-01', translate))
      .toBe('Alle 2 Woche(n) · 3 Folgeaufgaben · bis 2027-05-01');
  });
});

describe('task recurrence form', () => {
  it('offers each ordinary preset and saves the quarterly choice through the real form', async () => {
    await newTask();
    const select = screen.getByLabelText('Wiederholung');
    expect(within(select).getAllByRole('option').map(option => option.textContent)).toEqual([
      'Einmalig (ohne Wiederholung)', 'Täglich', 'Wöchentlich', 'Monatlich', 'Vierteljährlich', 'Halbjährlich', 'Jährlich', 'Benutzerdefiniert',
    ]);
    expect(screen.queryByLabelText('Serienregel (RRULE)')).not.toBeInTheDocument();
    change('Titel *', 'Quartalsprüfung'); change('Wiederholung', 'quarterly');
    submit();
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/tasks', expect.objectContaining({
      title: 'Quartalsprüfung', recurrence_rule: 'FREQ=MONTHLY;INTERVAL=3',
    })));
  });

  it('saves both custom limits and clears recurrence explicitly to null', async () => {
    const rendered = await newTask();
    change('Titel *', 'Kontrolle'); change('Wiederholung', 'custom');
    change('Häufigkeit', 'YEARLY'); change('Intervall', '2'); change('Ende der Wiederholung', 'both');
    change('Anzahl der Folgeaufgaben', '3'); change('Letzter Tag (einschließlich)', '2032-06-28');
    submit();
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/tasks', expect.objectContaining({
      recurrence_rule: 'FREQ=YEARLY;INTERVAL=2;COUNT=3;UNTIL=2032-06-28',
    })));
    rendered.unmount();
    state.tasks = [{ id: 'series', title: 'Serie', recurrence_rule: 'FREQ=MONTHLY;COUNT=12', updated_at: '2026-10-19T10:00:00Z' }];
    renderTasks();
    fireEvent.click(await screen.findByRole('button', { name: 'Serie bearbeiten' }));
    change('Wiederholung', 'none'); submit();
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/tasks/series', expect.objectContaining({ recurrence_rule: null, updated_at: state.tasks[0].updated_at })));
  });

  it.each([' count=003 ; freq=monthly ; until=2028-02-29 ; interval=02 ', 'FREQ=WEEKLY;UNTIL=2026W404'])(
    'preserves an existing series byte for byte when only its title changes: %s', async recurrence => {
      state.tasks = [{ id: 'series', title: 'Serie', recurrence_rule: recurrence, updated_at: '2026-10-19T10:00:00Z' }];
      renderTasks();
      fireEvent.click(await screen.findByRole('button', { name: 'Serie bearbeiten' }));
      change('Titel *', 'Geänderter Titel'); submit();
      await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/tasks/series', expect.objectContaining({ title: 'Geänderter Titel', recurrence_rule: recurrence })));
    });

  it('keeps an unrepresentable legacy rule visible and allows explicit correction without silent data loss', async () => {
    const recurrence = 'FREQ=MONTHLY;BYMONTHDAY=31';
    state.tasks = [{ id: 'series', title: 'Altbestand', recurrence_rule: recurrence }];
    renderTasks();
    fireEvent.click(await screen.findByRole('button', { name: 'Altbestand bearbeiten' }));
    expect(screen.getByLabelText('Wiederholung')).toHaveValue('custom');
    expect(screen.getByLabelText('Serienregel (RRULE)')).toHaveValue(recurrence);
    expect(api.patch).not.toHaveBeenCalled();
    change('Titel *', 'Titel bleibt'); submit();
    expect(await screen.findByRole('alert')).toHaveTextContent('Die Serienregel muss eine unterstützte Häufigkeit enthalten');
    expect(screen.getByLabelText('Serienregel (RRULE)')).toHaveValue(recurrence);
    expect(api.patch).not.toHaveBeenCalled();
    change('Serienregel (RRULE)', 'FREQ=MONTHLY;COUNT=5'); submit();
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/tasks/series', expect.objectContaining({ title: 'Titel bleibt', recurrence_rule: 'FREQ=MONTHLY;COUNT=5' })));
  });

  it('validates incomplete custom controls even on keyboard/form submission and retains the edits', async () => {
    await newTask();
    change('Titel *', 'Nicht verlieren'); change('Wiederholung', 'custom'); change('Intervall', '0');
    submit();
    expect(await screen.findByRole('alert')).toHaveTextContent('Das Intervall muss eine positive ganze Zahl sein.');
    expect(screen.getByLabelText('Wiederholung')).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByLabelText('Titel *')).toHaveValue('Nicht verlieren');
    expect(api.post).not.toHaveBeenCalled();
    change('Intervall', '2'); change('Ende der Wiederholung', 'count');
    submit();
    expect(await screen.findByRole('alert')).toHaveTextContent('Die Anzahl der Folgeaufgaben muss eine positive ganze Zahl sein.');
    change('Anzahl der Folgeaufgaben', '4'); submit();
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/tasks', expect.objectContaining({ recurrence_rule: 'FREQ=WEEKLY;INTERVAL=2;COUNT=4' })));
  });

  it.each([['en-US', 'Recurrence', 'Every six months'], ['es-ES', 'Repetición', 'Semestralmente']])(
    'uses localized controls in %s', async (locale, label, option) => {
      state.locale = locale;
      renderTasks();
      fireEvent.click(await screen.findByRole('button', { name: 'Neue Aufgabe' }));
      expect(within(screen.getByLabelText(label)).getByRole('option', { name: option })).toHaveValue('halfYearly');
    });

  it('restores unfinished custom recurrence through the actual draft writer and recovery flow', async () => {
    state.auth = { user: { id: 'task-owner' } };
    const first = await newTask();
    change('Titel *', 'Entwurf behalten'); change('Wiederholung', 'custom');
    change('Häufigkeit', 'MONTHLY'); change('Intervall', '2'); change('Ende der Wiederholung', 'both');
    change('Anzahl der Folgeaufgaben', '7'); change('Letzter Tag (einschließlich)', '2028-02-29');
    change('Intervall', '');
    await waitFor(() => expect(workspace.put).toHaveBeenCalledWith('drafts', expect.any(String), expect.objectContaining({
      values: expect.objectContaining({ recurrence_rule: 'FREQ=MONTHLY;INTERVAL=;COUNT=7;UNTIL=2028-02-29' }),
    })), { timeout: 2000 });
    first.unmount();
    renderTasks();
    fireEvent.click(await screen.findByRole('button', { name: 'Neue Aufgabe' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Entwurf wiederaufnehmen' }));
    await waitFor(() => expect(screen.getByLabelText('Intervall')).toBeEnabled());
    expect(screen.getByLabelText('Titel *')).toHaveValue('Entwurf behalten');
    expect(screen.getByLabelText('Wiederholung')).toHaveValue('custom');
    expect(screen.getByLabelText('Intervall')).toHaveValue(null);
    expect(screen.getByLabelText('Anzahl der Folgeaufgaben')).toHaveValue(7);
    expect(screen.getByLabelText('Letzter Tag (einschließlich)')).toHaveValue('2028-02-29');
    expect(api.post).not.toHaveBeenCalled();
    change('Intervall', '2'); submit();
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/tasks', expect.objectContaining({
      title: 'Entwurf behalten', recurrence_rule: 'FREQ=MONTHLY;INTERVAL=2;COUNT=7;UNTIL=2028-02-29',
    })));
    await waitFor(() => expect(workspace.remove).toHaveBeenCalled());
  });
});
