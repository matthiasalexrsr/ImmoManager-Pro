import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import DataTable from '../components/DataTable';

const columns = [
  { key: 'title', label: 'Titel', filterType: 'text' },
  { key: 'party', label: 'Partei', filterType: 'select' },
  { key: 'internal', label: 'Intern', hidden: true },
];
const rows = Array.from({ length: 30 }, (_, index) => ({
  id: `d-${index}`, title: `Dokument ${String(30 - index).padStart(2, '0')}`,
  party: 'Mia', internal: 'privat',
}));

function renderedTitles() {
  return within(screen.getByRole('table').tBodies[0]).getAllByRole('row')
    .map(row => within(row).getAllByRole('cell')[0].textContent);
}

function readBlob(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsText(blob);
  });
}

describe('DataTable server paging and complete CSV export', () => {
  let exportedBlob;
  let downloads;

  beforeEach(() => {
    localStorage.clear();
    exportedBlob = undefined;
    downloads = [];
    const NativeURL = globalThis.URL;
    vi.stubGlobal('URL', class extends NativeURL {
      static createObjectURL(blob) { exportedBlob = blob; return 'blob:csv-fixture'; }
      static revokeObjectURL() {}
    });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function () {
      downloads.push({ href: this.href, filename: this.download });
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('renders all supplied server rows in order without local controls or pagination', () => {
    const { container } = render(<DataTable columns={columns} data={rows} title="Dokumente" serverPaged />);

    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /filter/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    expect(container.querySelector('.table-footer')).toBeNull();
    expect(renderedTitles()).toHaveLength(30);
    expect(renderedTitles()[0]).toBe('Dokument 30');
    expect(renderedTitles()[29]).toBe('Dokument 01');
    const titleHeader = screen.getByRole('columnheader', { name: 'Titel' });
    expect(titleHeader).not.toHaveClass('sortable-th');
    fireEvent.click(titleHeader);
    expect(renderedTitles()[0]).toBe('Dokument 30');
    expect(screen.getByRole('button', { name: 'CSV' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /adjustColumns/ })).toBeInTheDocument();
  });

  it('ignores existing local search, column filters and sorting when server paging is enabled', () => {
    const { rerender } = render(<DataTable columns={columns} data={rows} title="Dokumente" />);
    fireEvent.click(screen.getByRole('columnheader', { name: 'Titel' }));
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Dokument 01' } });
    fireEvent.click(screen.getByRole('button', { name: /filter/i }));
    fireEvent.change(screen.getByPlaceholderText(/filterText/), { target: { value: 'unpassend' } });
    expect(screen.queryByText('Dokument 01')).not.toBeInTheDocument();

    rerender(<DataTable columns={columns} data={rows} title="Dokumente" serverPaged />);
    expect(renderedTitles()).toHaveLength(30);
    expect(renderedTitles()[0]).toBe('Dokument 30');
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /filter/i })).not.toBeInTheDocument();
  });

  it('preserves local search, sorting, pagination and complete filtered CSV by default', async () => {
    render(<DataTable columns={columns} data={rows} title="Dokumente" />);
    expect(screen.getByRole('textbox')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /filter/i })).toBeInTheDocument();
    expect(screen.getByRole('navigation')).toBeInTheDocument();
    expect(renderedTitles()).toHaveLength(25);
    fireEvent.click(screen.getByRole('button', { name: /nextPage/ }));
    expect(renderedTitles()).toHaveLength(5);
    expect(renderedTitles()[0]).toBe('Dokument 05');
    fireEvent.click(screen.getByRole('columnheader', { name: 'Titel' }));
    expect(renderedTitles()[0]).toBe('Dokument 01');
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Dokument 0' } });
    expect(renderedTitles()).toHaveLength(9);
    fireEvent.click(screen.getByRole('button', { name: 'CSV' }));
    await waitFor(() => expect(downloads).toHaveLength(1));
    const csv = await readBlob(exportedBlob);
    expect(csv.trim().split('\r\n')).toHaveLength(10);
    expect(csv).toContain('Titel;Partei');
    expect(csv).toContain('Dokument 01;Mia');
    expect(csv).not.toContain('Intern');
    expect(csv).not.toContain('Dokument 10');
  });

  it('exports all enriched loader rows beyond 25 using only currently visible columns', async () => {
    const completeRows = Array.from({ length: 63 }, (_, index) => ({
      id: `full-${index}`, title: `Voll ${index + 1}`, party: `Person ${index + 1}`, internal: 'SECRET',
    }));
    render(<DataTable columns={columns} data={rows.slice(0, 25)} title="Mias Dokumente"
      serverPaged loadExportData={async () => completeRows} />);
    fireEvent.click(screen.getByRole('button', { name: /adjustColumns/ }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Titel' }));
    fireEvent.click(screen.getByRole('button', { name: 'CSV' }));
    await waitFor(() => expect(downloads).toHaveLength(1));
    const csv = await readBlob(exportedBlob);
    expect(csv.trim().split('\r\n')).toHaveLength(64);
    expect(csv.trim().split('\r\n')[0]).toBe('Partei');
    expect(csv).toContain('Person 63');
    expect(csv).not.toContain('Mia');
    expect(csv).not.toContain('Voll 1');
    expect(csv).not.toContain('SECRET');
    expect(downloads[0].filename).toBe('Mias_Dokumente.csv');
  });

  it('keeps CSV busy without downloading partial rows while the complete loader is pending', async () => {
    let resolveExport;
    const pending = new Promise(resolve => { resolveExport = resolve; });
    render(<DataTable columns={columns} data={rows.slice(0, 25)} title="Dokumente"
      serverPaged loadExportData={() => pending} />);
    fireEvent.click(screen.getByRole('button', { name: 'CSV' }));
    const csvButton = screen.getByRole('button', { name: /CSV/ });
    expect(csvButton).toBeDisabled();
    expect(csvButton).toHaveAttribute('aria-busy', 'true');
    expect(downloads).toHaveLength(0);
    await act(async () => resolveExport([{ id: 'last', title: 'Komplett', party: 'Mia' }]));
    await waitFor(() => expect(downloads).toHaveLength(1));
    expect(csvButton).not.toBeDisabled();
  });

  it('shows failed exports inline and allows retry without downloading the current page', async () => {
    let attempts = 0;
    render(<DataTable columns={columns} data={rows.slice(0, 25)} title="Dokumente" serverPaged
      loadExportData={async () => {
        attempts += 1;
        if (attempts === 1) throw new Error('Export service failed');
        return [{ id: 'retry', title: 'Vollständiger Export', party: 'Mia' }];
      }} />);
    fireEvent.click(screen.getByRole('button', { name: 'CSV' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Export service failed');
    expect(downloads).toHaveLength(0);
    expect(exportedBlob).toBeUndefined();
    const csvButton = screen.getByRole('button', { name: 'CSV' });
    expect(csvButton).not.toBeDisabled();
    fireEvent.click(csvButton);
    await waitFor(() => expect(downloads).toHaveLength(1));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(await readBlob(exportedBlob)).toContain('Vollständiger Export;Mia');
  });

  it('rejects malformed export results without downloading an incomplete fallback', async () => {
    render(<DataTable columns={columns} data={rows.slice(0, 25)} title="Dokumente" serverPaged
      loadExportData={async () => ({ items: [] })} />);
    fireEvent.click(screen.getByRole('button', { name: 'CSV' }));
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(downloads).toHaveLength(0);
    expect(exportedBlob).toBeUndefined();
  });

  it('remembers sorting, rows per page and hidden columns for the same list', () => {
    const { unmount } = render(<DataTable columns={columns} data={rows} title="Dokumente" />);
    fireEvent.click(screen.getByRole('columnheader', { name: 'Titel' }));
    fireEvent.change(screen.getByRole('combobox', { name: 'Zeilen pro Seite' }), { target: { value: '10' } });
    fireEvent.click(screen.getByRole('button', { name: /adjustColumns/ }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Partei' }));
    unmount();

    render(<DataTable columns={columns} data={rows} title="Dokumente" />);
    expect(renderedTitles()).toHaveLength(10);
    expect(renderedTitles()[0]).toBe('Dokument 01');
    expect(screen.queryByRole('columnheader', { name: 'Partei' })).not.toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: 'Intern' })).not.toBeInTheDocument();
    cleanup();

    // another list keeps its own defaults
    render(<DataTable columns={columns} data={rows} title="Andere Liste" />);
    expect(renderedTitles()).toHaveLength(25);
    expect(renderedTitles()[0]).toBe('Dokument 30');
  });

  it('ignores stored settings it cannot use and works without browser storage', () => {
    localStorage.setItem('table_settings:/|Dokumente', JSON.stringify({ sortKey: 'gone', pageSize: 7, hiddenCols: 'x' }));
    render(<DataTable columns={columns} data={rows} title="Dokumente" />);
    expect(renderedTitles()).toHaveLength(25);
    expect(renderedTitles()[0]).toBe('Dokument 30');
    cleanup();

    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
    render(<DataTable columns={columns} data={rows} title="Dokumente" />);
    fireEvent.click(screen.getByRole('columnheader', { name: 'Titel' }));
    expect(renderedTitles()[0]).toBe('Dokument 01');
  });

  it('finds rows by the label the table shows, not only by the stored code', () => {
    const statusColumns = [{ key: 'title', label: 'Titel' }, { key: 'state', label: 'Status', type: 'status' }, { key: 'due', label: 'Fällig', type: 'date' }];
    const data = [
      { id: 'a', title: 'Offen A', state: 'open', due: '2026-10-14' },
      { id: 'b', title: 'Bezahlt B', state: 'paid', due: '2026-11-01' },
    ];
    render(<DataTable columns={statusColumns} data={data} title="Status" />);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '14.10.2026' } });
    expect(renderedTitles()).toEqual(['Offen A']);
  });

  it('writes CSV that German spreadsheets open in columns and that cannot run formulas', async () => {
    const moneyColumns = [{ key: 'title', label: 'Titel' }, { key: 'amount', label: 'Betrag', type: 'currency' }];
    const data = [
      { id: 'a', title: '=HYPERLINK("x")', amount: '1234.50' },
      { id: 'b', title: 'Gutschrift; Mai', amount: -12.5 },
      { id: 'c', title: '-Abzug', amount: null },
    ];
    render(<DataTable columns={moneyColumns} data={data} title="Beträge" />);
    fireEvent.click(screen.getByRole('button', { name: 'CSV' }));
    await waitFor(() => expect(downloads).toHaveLength(1));
    const lines = (await readBlob(exportedBlob)).replace(/^\ufeff/, '').split('\r\n');
    expect(lines).toEqual([
      'Titel;Betrag',
      `"'=HYPERLINK(""x"")";1234,50`,
      '"Gutschrift; Mai";-12,5',
      "'-Abzug;",
    ]);
  });

  it('finds search, filters and page as left when the list is opened again in the same tab', () => {
    const first = render(<DataTable columns={columns} data={rows} title="Dokumente" />);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Dokument' } });
    fireEvent.click(screen.getByRole('button', { name: /nextPage/ }));
    fireEvent.click(screen.getByRole('button', { name: /filter/i }));
    fireEvent.change(screen.getByPlaceholderText(/filterText/), { target: { value: 'Dok' } });
    fireEvent.click(screen.getByRole('button', { name: /nextPage/ }));
    expect(renderedTitles()[0]).toBe('Dokument 05');
    first.unmount();

    render(<DataTable columns={columns} data={rows} title="Dokumente" />);
    expect(screen.getByRole('textbox', { name: 'Dokumente durchsuchen' })).toHaveValue('Dokument');
    expect(screen.getByPlaceholderText(/filterText/)).toHaveValue('Dok');
    expect(renderedTitles()[0]).toBe('Dokument 05');
    cleanup();

    // a new tab, unusable saved values or a server-paged list start fresh
    sessionStorage.setItem('table_view:/|Dokumente', JSON.stringify({ search: 7, page: -2, columnFilters: { title: ['x'], gone: 'y' } }));
    render(<DataTable columns={columns} data={rows} title="Dokumente" />);
    expect(screen.getByRole('textbox', { name: 'Dokumente durchsuchen' })).toHaveValue('');
    expect(renderedTitles()).toHaveLength(25);
    cleanup();
    sessionStorage.clear();
    render(<DataTable columns={columns} data={rows} title="Dokumente" />);
    expect(renderedTitles()[0]).toBe('Dokument 30');
  });
});
