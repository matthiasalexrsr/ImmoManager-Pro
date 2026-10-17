import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import DataTable from '../components/DataTable';
import { privateStorageKey } from '../utils/workspaceIdentity';

vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => true, useAuth: () => null }));
beforeEach(() => localStorage.clear());
afterEach(() => cleanup());

const columns = [
  { key: 'title', label: 'Bezeichnung', filterType: 'text' },
  { key: 'amount', label: 'Betrag', type: 'number', filterType: 'numberRange' },
  { key: 'stage', label: 'Status', filterType: 'select' },
];
const data = [
  { id: '1', title: 'Nullbetrag', amount: 0, stage: 'open' },
  { id: '2', title: 'Betrag fehlt', amount: null, stage: 'open' },
  { id: '3', title: 'Bezahlt', amount: 12.5, stage: 'done' },
];

describe('Tabellenfilter: verständlich und ohne stille Fehlinterpretation', () => {
  it('zeigt klar beschriftete Bereichsfilter und behandelt fehlende Beträge nicht als Null', () => {
    render(<DataTable title="Prüfliste" columns={columns} data={data} />);
    fireEvent.click(screen.getByRole('button', { name: /ui.buttons.filter|Filter/i }));
    const minimum = screen.getByRole('spinbutton', { name: 'Betrag: Von' });
    expect(screen.getByRole('spinbutton', { name: 'Betrag: Bis' })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Bezeichnung filtern' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Status filtern' })).toBeInTheDocument();
    fireEvent.change(minimum, { target: { value: '0' } });
    const table = screen.getByRole('table', { name: 'Prüfliste' });
    expect(within(table).getByText('Nullbetrag')).toBeInTheDocument();
    expect(within(table).getByText('Bezahlt')).toBeInTheDocument();
    expect(within(table).queryByText('Betrag fehlt')).not.toBeInTheDocument();
  });

  it('macht Filter verborgener Spalten sichtbar und lässt sie einzeln entfernen', () => {
    render(<DataTable title="Prüfliste" columns={columns} data={data} />);
    fireEvent.click(screen.getByRole('button', { name: /ui.buttons.filter|Filter/i }));
    fireEvent.change(screen.getByRole('combobox', { name: 'Status filtern' }), { target: { value: 'open' } });
    expect(within(screen.getByRole('table', { name: 'Prüfliste' })).queryByText('Bezahlt')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'ui.table.adjustColumns' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Status' }));
    const group = screen.getByRole('group', { name: 'Aktive Tabellenfilter' });
    expect(within(group).getByRole('button', { name: 'Filter entfernen: Status' })).toBeInTheDocument();
    fireEvent.click(within(group).getByRole('button', { name: 'Filter entfernen: Status' }));
    expect(screen.queryByRole('group', { name: 'Aktive Tabellenfilter' })).not.toBeInTheDocument();
    expect(within(screen.getByRole('table', { name: 'Prüfliste' })).getByText('Bezahlt')).toBeInTheDocument();
  });

  it('verhindert eine Tabelle ohne sichtbare Datenspalte', () => {
    render(<DataTable title="Einträge" columns={[{ key: 'title', label: 'Bezeichnung' }]} data={data} />);
    fireEvent.click(screen.getByRole('button', { name: 'ui.table.adjustColumns' }));
    expect(screen.getByRole('checkbox', { name: 'Bezeichnung' })).toBeDisabled();
    expect(screen.getByRole('columnheader', { name: /Bezeichnung/ })).toBeInTheDocument();
  });

  it('entfernt einen verwaisten Vorgangsfokus über Zurücksetzen und zeigt wieder Treffer', () => {
    render(<MemoryRouter initialEntries={['/documents?focus_id=does-not-exist']}>
      <DataTable title="Dokumente" columns={columns} data={data} />
    </MemoryRouter>);
    expect(screen.getByText(/Keine Treffer/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Suche und Filter zurücksetzen/ }));
    expect(within(screen.getByRole('table', { name: 'Dokumente' })).getByText('Nullbetrag')).toBeInTheDocument();
  });
});


it('rettet eine gespeicherte Ansicht, in der alle Spalten ausgeblendet waren', () => {
  const key = privateStorageKey('table_settings:bad-all-hidden');
  localStorage.setItem(key, JSON.stringify({ hiddenCols: { title: true, amount: true, stage: true } }));
  render(<DataTable settingsKey="bad-all-hidden" title="Altansicht" columns={columns} data={data} />);
  const table = screen.getByRole('table', { name: 'Altansicht' });
  expect(within(table).getByRole('columnheader', { name: 'Bezeichnung' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'ui.table.adjustColumns' }));
  expect(screen.getByRole('checkbox', { name: 'Bezeichnung' })).toBeChecked();
  expect(screen.getByRole('checkbox', { name: 'Bezeichnung' })).toBeDisabled();
  expect(screen.getByRole('checkbox', { name: 'Betrag' })).not.toBeChecked();
});

it('bietet in Auswahlfiltern auch echte Null- und Falsch-Werte an', () => {
  const flags = [{ id: 'zero', flag: 0, title: 'Null' },
    { id: 'false', flag: false, title: 'Falsch' },
    { id: 'other', flag: 1, title: 'Eins' }];
  render(<DataTable title="Flaggen" columns={[
    { key: 'title', label: 'Titel' }, { key: 'flag', label: 'Merkmal', filterType: 'select' },
  ]} data={flags} />);
  fireEvent.click(screen.getByRole('button', { name: /ui.buttons.filter|Filter/i }));
  const choice = screen.getByRole('combobox', { name: 'Merkmal filtern' });
  expect(within(choice).getByRole('option', { name: '0' })).toBeInTheDocument();
  expect(within(choice).getByRole('option', { name: 'false' })).toBeInTheDocument();
  fireEvent.change(choice, { target: { value: 'false' } });
  const table = screen.getByRole('table', { name: 'Flaggen' });
  expect(within(table).getByText('Falsch')).toBeInTheDocument();
  expect(within(table).queryByText('Null')).not.toBeInTheDocument();
});


it('ein vollständig gelöschter Zahlenbereich zeigt auch Einträge ohne Betragswert wieder an', () => {
  render(<DataTable title="Betragsprüfung" columns={columns} data={data} />);
  fireEvent.click(screen.getByRole('button', { name: /ui.buttons.filter|Filter/i }));
  const minimum = screen.getByRole('spinbutton', { name: 'Betrag: Von' });
  fireEvent.change(minimum, { target: { value: '0' } });
  expect(within(screen.getByRole('table', { name: 'Betragsprüfung' })).queryByText('Betrag fehlt')).not.toBeInTheDocument();
  fireEvent.change(minimum, { target: { value: '' } });
  expect(within(screen.getByRole('table', { name: 'Betragsprüfung' })).getByText('Betrag fehlt')).toBeInTheDocument();
  expect(screen.queryByRole('group', { name: 'Aktive Tabellenfilter' })).not.toBeInTheDocument();
});

it('ein vollständig gelöschter Datumsbereich stellt undatierte Vorgänge wieder her', () => {
  const dated = [
    { id: '1', title: 'Mit Datum', date: '2026-10-17' },
    { id: '2', title: 'Noch kein Datum', date: null },
  ];
  render(<DataTable title="Termine" columns={[
    { key: 'title', label: 'Vorgang' },
    { key: 'date', label: 'Datum', type: 'date', filterType: 'dateRange' },
  ]} data={dated} />);
  fireEvent.click(screen.getByRole('button', { name: /ui.buttons.filter|Filter/i }));
  const from = screen.getByLabelText('Datum: Von');
  expect(screen.getByLabelText('Datum: Bis')).toBeInTheDocument();
  fireEvent.change(from, { target: { value: '2026-10-01' } });
  expect(within(screen.getByRole('table', { name: 'Termine' })).queryByText('Noch kein Datum')).not.toBeInTheDocument();
  fireEvent.change(from, { target: { value: '' } });
  expect(within(screen.getByRole('table', { name: 'Termine' })).getByText('Noch kein Datum')).toBeInTheDocument();
});


it('führt den Tastaturfokus sicher in die Spaltenauswahl und per Escape zurück', () => {
  render(<DataTable title="Fokusliste" columns={columns} data={data} />);
  const trigger = screen.getByRole('button', { name: 'ui.table.adjustColumns' });
  trigger.focus();
  fireEvent.click(trigger);
  const menu = screen.getByRole('group', { name: 'Spaltenauswahl' });
  const firstColumn = within(menu).getByRole('checkbox', { name: 'Bezeichnung' });
  expect(firstColumn).toHaveFocus();
  fireEvent.keyDown(firstColumn, { key: 'Escape' });
  expect(screen.queryByRole('group', { name: 'Spaltenauswahl' })).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
});

it('schließt die Spaltenauswahl beim Tab-Wechsel, ohne den externen Fokus zu übernehmen', () => {
  render(<DataTable title="Fokusliste" columns={columns} data={data} />);
  fireEvent.click(screen.getByRole('button', { name: 'ui.table.adjustColumns' }));
  const menu = screen.getByRole('group', { name: 'Spaltenauswahl' });
  expect(within(menu).getByRole('checkbox', { name: 'Bezeichnung' })).toHaveFocus();
  const search = screen.getByRole('textbox', { name: 'Fokusliste durchsuchen' });
  act(() => { search.focus(); fireEvent.focusIn(search); });
  expect(screen.queryByRole('group', { name: 'Spaltenauswahl' })).not.toBeInTheDocument();
  expect(search).toHaveFocus();
});


it('schließt ISO-Zeitstempel des ganzen lokalen Endtages ein, aber nicht den Folgetag', () => {
  // Date-time columns such as appointment_at, scheduled_at and changed_at
  // share the same day-range filter as date-only fields.
  const dated = [
    { id: '1', title: 'Früh am Endtag', changed_at: new Date(2026, 9, 17, 0, 15).toISOString() },
    { id: '2', title: 'Spät am Endtag', changed_at: new Date(2026, 9, 17, 23, 40).toISOString() },
    { id: '3', title: 'Erster Folgetag', changed_at: new Date(2026, 9, 18, 0, 5).toISOString() },
    { id: '4', title: 'Kalendertag ohne Uhrzeit', changed_at: '2026-10-17' },
    { id: '5', title: 'Ungültige Zeit', changed_at: 'kein-datum' },
  ];
  render(<DataTable title="Änderungshistorie" columns={[
    { key: 'title', label: 'Vorgang' },
    { key: 'changed_at', label: 'Geändert am', type: 'date', filterType: 'dateRange' },
  ]} data={dated} />);
  fireEvent.click(screen.getByRole('button', { name: /ui.buttons.filter|Filter/i }));
  fireEvent.change(screen.getByLabelText('Geändert am: Bis'), { target: { value: '2026-10-17' } });
  const table = screen.getByRole('table', { name: 'Änderungshistorie' });
  expect(within(table).getByText('Früh am Endtag')).toBeInTheDocument();
  expect(within(table).getByText('Spät am Endtag')).toBeInTheDocument();
  expect(within(table).getByText('Kalendertag ohne Uhrzeit')).toBeInTheDocument();
  expect(within(table).queryByText('Erster Folgetag')).not.toBeInTheDocument();
  expect(within(table).queryByText('Ungültige Zeit')).not.toBeInTheDocument();
});

it('zeigt Auswahlwerte mit identischer Darstellung nur einmal an', () => {
  render(<DataTable title="Statuswerte" columns={[
    { key: 'title', label: 'Titel' },
    { key: 'flag', label: 'Kennung', filterType: 'select' },
  ]} data={[
    { id: 'a', title: 'Numerisch', flag: 1 },
    { id: 'b', title: 'Als Text', flag: '1' },
    { id: 'c', title: 'Anders', flag: 2 },
  ]} />);
  fireEvent.click(screen.getByRole('button', { name: /ui.buttons.filter|Filter/i }));
  const selector = screen.getByRole('combobox', { name: 'Kennung filtern' });
  expect(within(selector).getAllByRole('option', { name: '1' })).toHaveLength(1);
  fireEvent.change(selector, { target: { value: '1' } });
  const table = screen.getByRole('table', { name: 'Statuswerte' });
  expect(within(table).getByText('Numerisch')).toBeInTheDocument();
  expect(within(table).getByText('Als Text')).toBeInTheDocument();
  expect(within(table).queryByText('Anders')).not.toBeInTheDocument();
});


it('nennt Screenreadern den betroffenen Datensatz zu gleichnamigen Bearbeiten- und Löschen-Aktionen', () => {
  const edit = vi.fn();
  const remove = vi.fn();
  render(<DataTable title="Objektliste" columns={[{ key: 'title', label: 'Immobilie' }]}
    data={[{ id: 'p1', title: 'Haus West' }, { id: 'p2', title: 'Haus Ost' }]}
    onEdit={edit} onDelete={remove} />);
  const table = screen.getByRole('table', { name: 'Objektliste' });
  for (const name of ['Haus West', 'Haus Ost']) {
    const row = within(table).getByRole('row', { name: new RegExp(name) });
    const buttons = within(row).getAllByRole('button');
    const editButton = buttons.find(button => button.getAttribute('aria-label')?.includes('edit'));
    const deleteButton = buttons.find(button => button.getAttribute('aria-label')?.includes('delete'));
    expect(editButton).toHaveAccessibleDescription(name);
    expect(deleteButton).toHaveAccessibleDescription(name);
  }
});
