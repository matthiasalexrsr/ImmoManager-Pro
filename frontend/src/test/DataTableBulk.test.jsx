import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import DataTable from '../components/DataTable';
import { bulkDelete } from '../utils/bulkActions';

const auth = vi.hoisted(() => ({ canWrite: true }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => auth.canWrite }));

const columns = [{ key: 'title', label: 'Titel' }, { key: 'status', label: 'Status' }];
const rows = Array.from({ length: 30 }, (_, i) => ({ id: `t${i + 1}`, title: `Aufgabe ${String(i + 1).padStart(2, '0')}`, status: i % 3 === 0 ? 'completed' : 'open' }));
const box = name => screen.getByRole('checkbox', { name: `Auswählen: ${name}` });

beforeEach(() => { localStorage.clear(); auth.canWrite = true; vi.stubGlobal('confirm', vi.fn(() => true)); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('DataTable bulk selection', () => {
  it('shows no selection column without actions or for a role that may not run them', () => {
    const { unmount } = render(<DataTable title="Aufgaben" columns={columns} data={rows} />);
    expect(screen.queryByRole('checkbox', { name: /Auswählen/ })).not.toBeInTheDocument();
    unmount();
    auth.canWrite = false;
    render(<DataTable title="Aufgaben" columns={columns} data={rows} bulkActions={[{ key: 'x', label: 'X', write: true, run: vi.fn() }]} />);
    expect(screen.queryByRole('checkbox', { name: /Auswählen/ })).not.toBeInTheDocument();
  });

  it('selects single rows, a shift range, the page and all matches, and runs only applicable rows', async () => {
    const run = vi.fn().mockResolvedValue(undefined);
    const finished = vi.fn();
    render(<DataTable title="Aufgaben" columns={columns} data={rows}
      bulkActions={[{ key: 'done', label: 'Erledigen', applies: row => row.status !== 'completed', run, finished }]} />);
    fireEvent.click(box('Aufgabe 01'));
    fireEvent.click(box('Aufgabe 05'), { shiftKey: true });
    const bar = screen.getByRole('region', { name: 'Auswahl' });
    expect(bar).toHaveTextContent('5 ausgewählt');
    // Aufgabe 01 and 04 are completed: the action names how many it affects
    expect(within(bar).getByRole('button', { name: 'Erledigen (3)' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('checkbox', { name: 'Alle Einträge dieser Seite auswählen' }));
    expect(bar).toHaveTextContent('25 ausgewählt');
    fireEvent.click(within(bar).getByRole('button', { name: 'Alle 30 Treffer auswählen' }));
    expect(bar).toHaveTextContent('30 ausgewählt');

    fireEvent.click(within(bar).getByRole('button', { name: 'Erledigen (20)' }));
    await waitFor(() => expect(finished).toHaveBeenCalledTimes(1));
    expect(run).toHaveBeenCalledTimes(20);
    expect(run.mock.calls.map(([row]) => row.id)).not.toContain('t1');
    // the 20 left the selection; the result stays until it is dismissed
    const result = screen.getByRole('status');
    expect(result).toHaveTextContent('Erledigen: 20 erledigt · 10 nicht betroffen');
    expect(screen.getByRole('region', { name: 'Auswahl' })).toHaveTextContent('10 ausgewählt');
    fireEvent.click(screen.getByRole('button', { name: 'Auswahl aufheben' }));
    expect(screen.getByRole('status')).toHaveTextContent('20 erledigt');
    fireEvent.click(screen.getByRole('button', { name: 'Schließen' }));
    expect(screen.queryByRole('region', { name: 'Auswahl' })).not.toBeInTheDocument();
  });

  it('acts only on rows the search still shows', async () => {
    const run = vi.fn().mockResolvedValue(undefined);
    render(<DataTable title="Aufgaben" columns={columns} data={rows} bulkActions={[{ key: 'x', label: 'Archivieren', run }]} />);
    fireEvent.click(screen.getByRole('checkbox', { name: 'Alle Einträge dieser Seite auswählen' }));
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Aufgabe 0' } });
    const bar = screen.getByRole('region', { name: 'Auswahl' });
    expect(bar).toHaveTextContent('9 ausgewählt');
    fireEvent.click(within(bar).getByRole('button', { name: 'Archivieren' }));
    await waitFor(() => expect(run).toHaveBeenCalledTimes(9));
  });

  it('asks before deleting, reports failed rows and keeps only them selected', async () => {
    const remove = vi.fn(row => (row.id === 't2' ? Promise.reject(new Error('Wird noch von 1 Buchung verwendet')) : Promise.resolve()));
    const finished = vi.fn();
    render(<DataTable title="Aufgaben" columns={columns} data={rows} rowName={row => row.title}
      bulkActions={[bulkDelete({ one: 'Aufgabe', many: 'Aufgaben', remove, finished })]} />);
    fireEvent.click(box('Aufgabe 01'));
    fireEvent.click(box('Aufgabe 03'), { shiftKey: true });
    window.confirm.mockReturnValueOnce(false);
    fireEvent.click(screen.getByRole('button', { name: 'Löschen' }));
    await waitFor(() => expect(window.confirm).toHaveBeenCalledWith('3 Aufgaben löschen? Diese Aktion kann nicht rückgängig gemacht werden.'));
    expect(remove).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Löschen' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Löschen: 2 erledigt · 1 fehlgeschlagen');
    expect(alert).toHaveTextContent('Aufgabe 02: Wird noch von 1 Buchung verwendet');
    expect(finished).toHaveBeenCalledWith(expect.objectContaining({ failed: [expect.objectContaining({ row: rows[1] })] }));
    expect(screen.getByRole('region', { name: 'Auswahl' })).toHaveTextContent('1 ausgewählt');
    expect(box('Aufgabe 02')).toBeChecked();
    expect(box('Aufgabe 01')).not.toBeChecked();
  });

  it('drops rows that left the list from the selection', () => {
    const props = { title: 'Aufgaben', columns, bulkActions: [{ key: 'x', label: 'X', run: vi.fn() }] };
    const { rerender } = render(<DataTable {...props} data={rows} />);
    fireEvent.click(box('Aufgabe 01'));
    fireEvent.click(box('Aufgabe 02'));
    rerender(<DataTable {...props} data={rows.slice(1)} />);
    expect(screen.getByRole('region', { name: 'Auswahl' })).toHaveTextContent('1 ausgewählt');
  });

  it('a checkbox click does not open the row', () => {
    const onRowClick = vi.fn();
    render(<DataTable title="Aufgaben" columns={columns} data={rows} onRowClick={onRowClick} bulkActions={[{ key: 'x', label: 'X', run: vi.fn() }]} />);
    fireEvent.click(box('Aufgabe 01'));
    expect(onRowClick).not.toHaveBeenCalled();
  });
});
