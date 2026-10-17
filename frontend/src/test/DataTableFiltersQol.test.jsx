import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
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
