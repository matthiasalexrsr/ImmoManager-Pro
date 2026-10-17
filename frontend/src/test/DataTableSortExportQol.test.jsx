import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import DataTable from '../components/DataTable';

vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => true, useAuth: () => null }));

const namedRows = () => within(screen.getByRole('table').tBodies[0])
  .getAllByRole('row').map(row => within(row).getAllByRole('cell')[0].textContent);
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};

beforeEach(() => { localStorage.clear(); sessionStorage.clear(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('Tabellensortierung ohne irreführende Leerwerte', () => {
  it('sortiert Bezeichnungen natürlich, einschließlich nummerierter Einheiten', () => {
    render(<DataTable title="Einheiten" columns={[{ key: 'name', label: 'Name' }]}
      data={[{ id: 10, name: 'Wohnung 10' }, { id: 2, name: 'Wohnung 2' }, { id: 1, name: 'Wohnung 1' }]} />);
    fireEvent.click(screen.getByRole('columnheader', { name: 'Name' }));
    expect(namedRows()).toEqual(['Wohnung 1', 'Wohnung 2', 'Wohnung 10']);
    fireEvent.click(screen.getByRole('columnheader', { name: 'Name' }));
    expect(namedRows()).toEqual(['Wohnung 10', 'Wohnung 2', 'Wohnung 1']);
  });

  it('behandelt fehlende und ungültige Beträge nicht als echten Nullbetrag', () => {
    render(<DataTable title="Buchungen" columns={[
      { key: 'name', label: 'Name' },
      { key: 'amount', label: 'Betrag', type: 'number' },
    ]} data={[
      { id: 'missing', name: 'Nicht erfasst', amount: null },
      { id: 'zero', name: 'Nullbetrag', amount: 0 },
      { id: 'other', name: 'Zahlung', amount: 25 },
      { id: 'wrong', name: 'Ungültig', amount: 'keine Zahl' },
      { id: 'negative', name: 'Gutschrift', amount: -5 },
    ]} />);
    fireEvent.click(screen.getByRole('columnheader', { name: 'Betrag' }));
    expect(namedRows()).toEqual(['Gutschrift', 'Nullbetrag', 'Zahlung', 'Nicht erfasst', 'Ungültig']);
    fireEvent.click(screen.getByRole('columnheader', { name: 'Betrag' }));
    expect(namedRows()).toEqual(['Zahlung', 'Nullbetrag', 'Gutschrift', 'Nicht erfasst', 'Ungültig']);
  });

  it('stellt undatierte und ungültig datierte Vorgänge in beiden Richtungen ans Ende', () => {
    render(<DataTable title="Termine" columns={[
      { key: 'name', label: 'Name' }, { key: 'date', label: 'Datum', type: 'date' },
    ]} data={[
      { id: 'missing', name: 'Ohne Datum', date: null },
      { id: 'future', name: 'Später', date: '2026-11-10' },
      { id: 'bad', name: 'Fehlerhaft', date: 'not-a-date' },
      { id: 'past', name: 'Früher', date: '2026-10-10' },
    ]} />);
    fireEvent.click(screen.getByRole('columnheader', { name: 'Datum' }));
    expect(namedRows()).toEqual(['Früher', 'Später', 'Ohne Datum', 'Fehlerhaft']);
    fireEvent.click(screen.getByRole('columnheader', { name: 'Datum' }));
    expect(namedRows()).toEqual(['Später', 'Früher', 'Ohne Datum', 'Fehlerhaft']);
  });
});

describe('CSV-Export mit klaren Abbruchgrenzen', () => {
  let downloads;
  let blobs;
  beforeEach(() => {
    downloads = []; blobs = [];
    const RealURL = globalThis.URL;
    vi.stubGlobal('URL', class extends RealURL {
      static createObjectURL(blob) { blobs.push(blob); return 'blob:export-test'; }
      static revokeObjectURL() {}
    });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function () {
      downloads.push({ filename: this.download, href: this.href });
    });
  });

  const columns = [{ key: 'name', label: 'Bezeichnung' }];
  const page = [{ id: 'one', name: 'Nur aktuelle Seite' }];

  it('verhindert mehrfache Datenladung während eines verzögerten Exports', async () => {
    const pending = deferred();
    const loader = vi.fn(() => pending.promise);
    render(<DataTable title="Gesamtbestand" columns={columns} data={page}
      serverPaged loadExportData={loader} />);
    const button = screen.getByRole('button', { name: 'CSV' });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(loader).toHaveBeenCalledTimes(1);
    expect(button).toBeDisabled();
    await act(async () => pending.resolve([{ id: 'full', name: 'Gesamte Datei' }]));
    await waitFor(() => expect(downloads).toHaveLength(1));
  });

  it('lädt nach Verlassen der Seite keine privaten Exportdaten nachträglich herunter', async () => {
    const pending = deferred();
    const { unmount } = render(<DataTable title="Private Akten" columns={columns}
      data={page} serverPaged loadExportData={() => pending.promise} />);
    fireEvent.click(screen.getByRole('button', { name: 'CSV' }));
    unmount();
    await act(async () => pending.resolve([{ id: 'private', name: 'Private Akten' }]));
    expect(downloads).toHaveLength(0);
    expect(blobs).toHaveLength(0);
  });

  it('verwirft den alten Export bei einem Wechsel des Benutzerkontos', async () => {
    const pending = deferred();
    render(<DataTable title="Private Akten" columns={columns} data={page}
      serverPaged loadExportData={() => pending.promise} />);
    fireEvent.click(screen.getByRole('button', { name: 'CSV' }));
    act(() => { window.dispatchEvent(new CustomEvent('workspace-owner', { detail: 'other-user' })); });
    await act(async () => pending.resolve([{ id: 'private', name: 'Vorgang des früheren Kontos' }]));
    expect(downloads).toHaveLength(0);
    expect(blobs).toHaveLength(0);
  });

  it('erstellt unter Windows gültige Dateinamen auch aus Seitentiteln mit Sonderzeichen', async () => {
    render(<DataTable title="Abrechnung / 2026: P1?" columns={columns} data={page} />);
    fireEvent.click(screen.getByRole('button', { name: 'CSV' }));
    await waitFor(() => expect(downloads).toHaveLength(1));
    expect(downloads[0].filename).toBe('Abrechnung_2026_P1.csv');
  });

  it('vermeidet unter Windows reservierte Gerätenamen und Steuerzeichen im CSV-Dateinamen', async () => {
    const first = render(<DataTable title="CON" columns={columns} data={page} />);
    fireEvent.click(screen.getByRole('button', { name: 'CSV' }));
    await waitFor(() => expect(downloads).toHaveLength(1));
    expect(downloads[0].filename).toBe('Export_CON.csv');
    first.unmount();

    render(<DataTable title={'Miete\u0000 Oktober'} columns={columns} data={page} />);
    fireEvent.click(screen.getByRole('button', { name: 'CSV' }));
    await waitFor(() => expect(downloads).toHaveLength(2));
    expect(downloads[1].filename).toBe('Miete_Oktober.csv');
  });
});
