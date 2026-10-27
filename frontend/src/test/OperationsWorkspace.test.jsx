import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import Calendar from '../pages/Calendar';
import Maintenance from '../pages/Maintenance';
import { api } from '../api';
import { localDateTimeInput, saveLocalDateTime } from '../utils/dateTimeInput';

const state = vi.hoisted(() => ({ lookups: {}, lookupError: null, invalidate: vi.fn(), reload: vi.fn() }));
vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), del: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: 'de-DE', t: key => ({
  'ui.buttons.save': 'Speichern', 'ui.buttons.cancel': 'Abbrechen', 'ui.buttons.close': 'Schließen',
}[key]) }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => async () => true }));
vi.mock('../contexts/DataStoreContext', () => ({
  useDataStore: () => ({ invalidateRelated: state.invalidate }),
  useEntities: key => ({ items: state.lookups[key] || [], loading: false, error: state.lookupError, reload: state.reload }),
}));
vi.mock('../components/DataTable', () => ({ default: ({ data, columns, onAdd, onEdit, onDelete }) => <section aria-label="Ergebnisliste">
  {onAdd && <button type="button" onClick={() => onAdd()}>Neu</button>}
  {data.map(row => <article key={row.id} data-testid={row.id}>
    {columns.filter(column => !column.hidden).map(column => <span key={column.key}>
      {column.render ? column.render(row[column.key], row) : row[column.key]}</span>)}
    {onEdit && <button type="button" onClick={() => onEdit(row)}>Bearbeiten</button>}
    {onDelete && <button type="button" onClick={() => onDelete(row)}>Löschen</button>}
  </article>)}
</section> }));

const caseRecord = { id: 'case', title: 'Dach prüfen', property_id: 'p1', unit_id: 'u1', status: 'open',
  priority: 'medium', category: 'Dach', appointment_at: '2026-11-03T14:35:27.123+01:00', updated_at: '2026-10-21T10:00:00Z' };
const eventRecord = { id: 'event', title: 'Ablesetermin', event_type: 'meeting', event_date: '2026-11-03',
  event_time: '14:35', property_id: 'p1', unit_id: 'u1', updated_at: '2026-10-21T10:00:00Z' };
let cases, events;
beforeEach(() => {
  vi.resetAllMocks(); sessionStorage.clear(); localStorage.clear();
  state.lookupError = null;
  state.lookups = { properties: [{ id: 'p1', name: 'Haus Nord' }, { id: 'p2', name: 'Haus Süd' }],
    units: [{ id: 'u1', property_id: 'p1', label: 'Nord 1' }, { id: 'u2', property_id: 'p2', label: 'Süd 1' }] };
  cases = [{ ...caseRecord }]; events = [{ ...eventRecord }];
  api.get.mockResolvedValue({});
  api.list.mockImplementation(path => Promise.resolve(path.startsWith('/calendar') ? events
    : path === '/properties' ? state.lookups.properties : cases));
  api.put.mockResolvedValue({}); api.post.mockResolvedValue({}); api.del.mockResolvedValue(null);
});
afterEach(cleanup);
const show = (Component, path) => render(<MemoryRouter initialEntries={[path]}><Component /></MemoryRouter>);

describe('operational files', () => {
  it('creates a case in its originating unit and restricts unit choices to its property', async () => {
    show(Maintenance, '/maintenance?unit_id=u1');
    fireEvent.click(await screen.findByRole('button', { name: 'Neu' }));
    expect(screen.getByLabelText('Immobilie *')).toHaveValue('p1');
    expect(screen.getByLabelText('Einheit')).toHaveValue('u1');
    expect(within(screen.getByLabelText('Einheit')).queryByRole('option', { name: 'Süd 1' })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Immobilie *'), { target: { value: 'p2' } });
    expect(screen.getByLabelText('Einheit')).toHaveValue('');
    expect(within(screen.getByLabelText('Einheit')).getByRole('option', { name: 'Süd 1' })).toBeInTheDocument();
  });

  it('preserves the complete original appointment instant when editing another field', async () => {
    show(Maintenance, '/maintenance');
    fireEvent.click(await screen.findByRole('button', { name: 'Bearbeiten' }));
    expect(screen.getByLabelText('Termin').value.replace(/\.000$/, '')).toBe(localDateTimeInput(caseRecord.appointment_at));
    expect(screen.getByLabelText('Termin')).toHaveAttribute('step', '1');
    fireEvent.change(screen.getByLabelText('Titel *'), { target: { value: 'Dach und Rinne prüfen' } });
    fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith('/maintenance/case', expect.objectContaining({
      title: 'Dach und Rinne prüfen', appointment_at: caseRecord.appointment_at, updated_at: caseRecord.updated_at })));
    expect(state.invalidate).toHaveBeenCalledWith('maintenance', 'properties', 'units', 'calendar');
  });

  it('shows failed object choices instead of offering an incomplete new form', async () => {
    state.lookupError = 'Objektdaten nicht erreichbar';
    show(Maintenance, '/maintenance');
    await screen.findByText('Dach prüfen');
    expect(screen.getAllByRole('alert')[0]).toHaveTextContent('Objektdaten nicht erreichbar');
    expect(screen.queryByRole('button', { name: 'Neu' })).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByRole('button', { name: 'Auswahl erneut laden' })[0]);
    expect(state.reload).toHaveBeenCalledOnce();
  });

  it('passes object and date context to the calendar and prefills new appointments', async () => {
    show(Calendar, '/calendar?unit_id=u1&date_from=2026-11-01&date_to=2026-11-30');
    fireEvent.click(await screen.findByRole('button', { name: 'Neu' }));
    expect(api.list).toHaveBeenCalledWith('/calendar?unit_id=u1&date_from=2026-11-01&date_to=2026-11-30', expect.anything());
    expect(screen.getByLabelText('Immobilie')).toHaveValue('p1');
    expect(screen.getByLabelText('Einheit (optional)')).toHaveValue('u1');
    expect(screen.getByLabelText('Datum *')).toHaveValue('2026-11-01');
  });

  it('links a project event to its actual case and shows all appointment details', async () => {
    events = [{ ...eventRecord, maintenance_case_id: 'case', description: 'Dachboden prüfen', participants: 'Dach Müller' }];
    show(Calendar, '/calendar?maintenance_case_id=case&focus_id=event');
    const details = await screen.findByRole('region', { name: 'Termindetails' });
    expect(within(details).getByText('Dachboden prüfen')).toBeInTheDocument();
    expect(within(details).getByRole('link', { name: /Projektakte und Termin/ })).toHaveAttribute('href', '/maintenance/case?tab=appointments');
    expect(within(screen.getByRole('region', { name: 'Ergebnisliste' })).getByRole('link', { name: 'Ablesetermin' }))
      .toHaveAttribute('href', '/maintenance/case?tab=appointments');
    expect(screen.queryByRole('button', { name: 'Neu' })).not.toBeInTheDocument();
  });

  it('keeps historic free-text times and the captured revision when saving', async () => {
    events = [{ ...eventRecord, event_time: 'nach Absprache' }];
    show(Calendar, '/calendar');
    fireEvent.click(await screen.findByRole('button', { name: 'Bearbeiten' }));
    expect(screen.getByLabelText('Uhrzeit')).toHaveAttribute('type', 'text');
    fireEvent.change(screen.getByLabelText('Titel *'), { target: { value: 'Ablesung besprechen' } });
    fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith('/calendar/event', expect.objectContaining({
      event_time: 'nach Absprache', updated_at: eventRecord.updated_at })));
    expect(state.invalidate).toHaveBeenCalledWith('calendar', 'maintenance', 'properties', 'units');
  });

  it('retains loaded calendar rows and clearly reports a failed refresh', async () => {
    show(Calendar, '/calendar');
    await screen.findByText('Ablesetermin');
    api.list.mockRejectedValue(new Error('Verbindung unterbrochen'));
    fireEvent.click(screen.getByRole('button', { name: 'Alle Termine' }));
    fireEvent.click(screen.getByRole('button', { name: 'Löschen' }));
    expect(await screen.findByText(/Angezeigt wird der zuletzt geladene Stand/)).toBeInTheDocument();
    expect(screen.getByText('Ablesetermin')).toBeInTheDocument();
  });
});

describe('local appointment inputs', () => {
  it('round trips the exact original, including seconds, fractions and offset', () => {
    for (const original of [caseRecord.appointment_at, '2026-10-25T02:30:57.023+02:00', '2026-10-25T02:30:57.023+01:00']) {
      expect(saveLocalDateTime(localDateTimeInput(original), original)).toBe(original);
      expect(saveLocalDateTime(localDateTimeInput(original) + '.000', original)).toBe(original);
    }
  });
  it('saves changed local wall times without an implicit SQL time zone conversion and supports clearing', () => {
    const local = localDateTimeInput('2026-11-04T15:45:00Z');
    expect(saveLocalDateTime(local, caseRecord.appointment_at)).toBe(local);
    expect(saveLocalDateTime('', caseRecord.appointment_at)).toBeNull();
    expect(() => saveLocalDateTime('ungültig')).toThrow(/gültiges Datum/);
  });
});
