import { Blob as NativeBlob } from 'node:buffer';
import { afterEach, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import DataTable from '../components/DataTable';
import german from '../../../i18n/de-DE.json';

vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key.split('.').reduce((value, part) => value?.[part], german) || key }) }));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const names = () => [...screen.getByRole('table').querySelectorAll('tbody tr')].map(row => row.cells[0].textContent);
const base = [{ key: 'name', label: 'Name' }, { key: 'amount', label: 'Betrag', type: 'number', filterType: 'numberRange' }];

it('supports keyboard sorting with numeric zero, missing values last, and a return to original order', async () => {
  const user = userEvent.setup();
  render(<DataTable title="Konten" columns={base} data={[{ name: 'Zehn', amount: 10 }, { name: 'Fehlt', amount: null }, { name: 'Null', amount: 0 }, { name: 'Zwei', amount: 2 }]} />);
  const button = screen.getByRole('button', { name: 'Betrag', exact: true });
  button.focus();
  await user.keyboard('{Enter}');
  expect(names()).toEqual(['Null', 'Zwei', 'Zehn', 'Fehlt']);
  expect(screen.getByRole('columnheader', { name: 'Betrag' })).toHaveAttribute('aria-sort', 'ascending');
  await user.keyboard(' ');
  expect(names()).toEqual(['Zehn', 'Zwei', 'Null', 'Fehlt']);
  await user.keyboard('{Enter}');
  expect(names()).toEqual(['Zehn', 'Fehlt', 'Null', 'Zwei']);
  expect(screen.getByRole('columnheader', { name: 'Betrag' })).toHaveAttribute('aria-sort', 'none');
});

it('searches zero and false values and clearing search restores focus and all rows', () => {
  render(<DataTable title="Werte" columns={[{ key: 'name', label: 'Name' }, { key: 'value', label: 'Wert' }]} data={[{ name: 'Null', value: 0 }, { name: 'Falsch', value: false }, { name: 'Leer', value: null }]} />);
  const input = screen.getByRole('textbox', { name: 'Suchen Werte' });
  fireEvent.change(input, { target: { value: '0' } });
  expect(names()).toEqual(['Null']);
  fireEvent.change(input, { target: { value: 'false' } });
  expect(names()).toEqual(['Falsch']);
  fireEvent.click(screen.getByRole('button', { name: 'Suche leeren' }));
  expect(input).toHaveFocus();
  expect(names()).toEqual(['Null', 'Falsch', 'Leer']);
});

it('keeps zero and false options selectable and searchable through column text filters', () => {
  const columns = [{ key: 'name', label: 'Name' }, { key: 'value', label: 'Wert', filterType: 'select' }, { key: 'flag', label: 'Flag', filterType: 'text' }];
  render(<DataTable title="Werte" columns={columns} data={[{ name: 'Null', value: 0, flag: false }, { name: 'Falsch', value: false, flag: true }, { name: 'Leer', value: null, flag: null }]} />);
  const select = screen.getByRole('combobox', { name: 'Filtern · Wert' });
  expect(within(select).getByRole('option', { name: '0' })).toBeInTheDocument();
  expect(within(select).getByRole('option', { name: 'false' })).toBeInTheDocument();
  fireEvent.change(select, { target: { value: 'false' } });
  expect(names()).toEqual(['Falsch']);
  fireEvent.change(select, { target: { value: '' } });
  fireEvent.change(screen.getByRole('textbox', { name: 'Filtern · Flag' }), { target: { value: 'false' } });
  expect(names()).toEqual(['Null']);
});

it('does not treat missing numbers as zero and clearing a range restores missing records', () => {
  render(<DataTable title="Konten" columns={base} data={[{ name: 'Null', amount: 0 }, { name: 'Fehlt', amount: null }, { name: 'Leer', amount: '' }, { name: 'Zwei', amount: 2 }]} />);
  const min = screen.getByRole('spinbutton', { name: 'Betrag · Min' });
  const max = screen.getByRole('spinbutton', { name: 'Betrag · Max' });
  fireEvent.change(min, { target: { value: '0' } });
  fireEvent.change(max, { target: { value: '0' } });
  expect(names()).toEqual(['Null']);
  fireEvent.change(min, { target: { value: '' } });
  fireEvent.change(max, { target: { value: '' } });
  expect(names()).toEqual(['Null', 'Fehlt', 'Leer', 'Zwei']);
  expect(screen.queryByRole('button', { name: 'Filter ✕' })).not.toBeInTheDocument();
});

it('cleared date range is inactive rather than hiding records without a date', () => {
  render(<DataTable title="Termine" columns={[{ key: 'name', label: 'Name' }, { key: 'date', label: 'Datum', filterType: 'dateRange' }]} data={[{ name: 'Datiert', date: '2026-10-01' }, { name: 'Ohne Datum', date: null }]} />);
  const from = screen.getByLabelText('Datum · Von');
  fireEvent.change(from, { target: { value: '2026-09-01' } });
  expect(names()).toEqual(['Datiert']);
  fireEvent.change(from, { target: { value: '' } });
  expect(names()).toEqual(['Datiert', 'Ohne Datum']);
});

it('uses the visible page when navigating after a data refresh reduces the page count', () => {
  const rows = Array.from({ length: 66 }, (_, i) => ({ id: i, name: `Eintrag ${i + 1}` }));
  const { rerender } = render(<DataTable title="Einträge" columns={[{ key: 'name', label: 'Name' }]} data={rows} />);
  fireEvent.change(screen.getByRole('combobox', { name: 'Einträge pro Seite' }), { target: { value: '10' } });
  fireEvent.click(screen.getByRole('button', { name: 'Letzte Seite' }));
  expect(names()).toHaveLength(6);
  rerender(<DataTable title="Einträge" columns={[{ key: 'name', label: 'Name' }]} data={rows.slice(0, 11)} />);
  expect(names()).toEqual(['Eintrag 11']);
  fireEvent.click(screen.getByRole('button', { name: 'Vorherige Seite' }));
  expect(names()[0]).toBe('Eintrag 1');
  expect(screen.getByRole('button', { name: 'Vorherige Seite' })).toBeDisabled();
});

it('keeps the same idless row controls attached to their record when sorted', () => {
  const rows = [{ name: 'Beta' }, { name: 'Alpha' }];
  const columns = [{ key: 'name', label: 'Name', render: name => <input aria-label={name} defaultValue={name} /> }];
  render(<DataTable title="Entwürfe" columns={columns} data={rows} />);
  const beta = screen.getByRole('textbox', { name: 'Beta' });
  fireEvent.change(beta, { target: { value: 'Bearbeiteter Beta-Entwurf' } });
  fireEvent.click(screen.getByRole('button', { name: 'Name', exact: true }));
  expect(screen.getByRole('textbox', { name: 'Beta' })).toBe(beta);
  expect(beta).toHaveValue('Bearbeiteter Beta-Entwurf');
  expect(screen.getByRole('table').querySelector('tbody tr input')).toHaveAttribute('aria-label', 'Alpha');
});

it('custom interactive cells do not trigger row navigation, while the row remains keyboard accessible', () => {
  const onRow = vi.fn(), onAction = vi.fn();
  const row = { id: 1, name: 'Mieter', action: 'Öffnen' };
  render(<DataTable title="Mieter" columns={[{ key: 'name', label: 'Name' }, { key: 'action', label: 'Aktion', render: value => <button type="button" onClick={onAction}>{value}</button> }]} data={[row]} onRowClick={onRow} />);
  fireEvent.click(screen.getByRole('button', { name: 'Öffnen' }));
  expect(onAction).toHaveBeenCalledTimes(1);
  expect(onRow).not.toHaveBeenCalled();
  const dataRow = screen.getByText('Mieter', { selector: 'td' }).closest('tr');
  fireEvent.keyDown(dataRow, { key: 'Enter' });
  expect(onRow).toHaveBeenCalledWith(row);
  fireEvent.click(screen.getByText('Mieter', { selector: 'td' }));
  expect(onRow).toHaveBeenCalledTimes(2);
});

it('column popup protects the final data column and Escape consumes the popup before returning focus', () => {
  const outerEscape = vi.fn();
  render(<div onKeyDown={outerEscape}><DataTable title="Konten" columns={base} data={[{ name: 'Null', amount: 0 }]} /></div>);
  const toggle = screen.getByRole('button', { name: 'Spalten anpassen' });
  fireEvent.click(toggle);
  const name = screen.getByRole('checkbox', { name: 'Name' });
  expect(name).toHaveFocus();
  fireEvent.click(name);
  expect(screen.getByRole('checkbox', { name: 'Betrag' })).toBeDisabled();
  fireEvent.keyDown(name, { key: 'Escape' });
  expect(outerEscape).not.toHaveBeenCalled();
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  expect(toggle).toHaveFocus();
  fireEvent.click(toggle);
  fireEvent.click(screen.getByRole('button', { name: 'Spalten zurücksetzen' }));
  expect(screen.getByRole('checkbox', { name: 'Name' })).toBeChecked();
  expect(screen.getByRole('checkbox', { name: 'Betrag' })).toBeChecked();
});

it('table search and filter Enter do not implicitly submit an enclosing preview form', async () => {
  const user = userEvent.setup(), submit = vi.fn(event => event.preventDefault());
  render(<form onSubmit={submit}><DataTable title="Vorschau" columns={[{ key: 'name', label: 'Name', filterType: 'text' }]} data={[{ name: 'Miete' }]} onAdd={vi.fn()} onEdit={vi.fn()} onDelete={vi.fn()} /><button type="submit">Generieren</button><input aria-label="Eigene Formularangabe" /></form>);
  screen.getByRole('textbox', { name: 'Suchen Vorschau' }).focus();
  await user.keyboard('{Enter}');
  screen.getByRole('textbox', { name: 'Filtern · Name' }).focus();
  await user.keyboard('{Enter}');
  expect(submit).not.toHaveBeenCalled();
  for (const button of screen.getByRole('table').closest('.data-table-wrapper').querySelectorAll('button')) expect(button).toHaveAttribute('type', 'button');
  screen.getByRole('textbox', { name: 'Eigene Formularangabe' }).focus();
  await user.keyboard('{Enter}');
  expect(submit).toHaveBeenCalledTimes(1);
});

it('CSV escapes headers and values consistently, including quotes and carriage returns', async () => {
  let downloaded;
  vi.stubGlobal('Blob', NativeBlob);
  vi.stubGlobal('URL', { createObjectURL: vi.fn(blob => { downloaded = blob; return 'blob:synthetic'; }), revokeObjectURL: vi.fn() });
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  render(<DataTable title="Export" columns={[{ key: 'name', label: 'Name,"Titel"\rZeile' }, { key: 'value', label: 'Wert' }]} data={[{ name: 'Text,"Zitat"\rEnde', value: 0 }]} />);
  fireEvent.click(screen.getByRole('button', { name: 'CSV' }));
  expect([...new Uint8Array(await downloaded.arrayBuffer()).slice(0, 3)]).toEqual([239, 187, 191]);
  expect(await downloaded.text()).toBe('"Name,""Titel""\rZeile",Wert\n"Text,""Zitat""\rEnde",0');
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:synthetic');
});

it('filtered empty state offers a working reset without resetting the row data', () => {
  render(<DataTable title="Liste" columns={[{ key: 'name', label: 'Name' }]} data={[{ name: 'Mieter' }]} />);
  fireEvent.change(screen.getByRole('textbox', { name: 'Suchen Liste' }), { target: { value: 'Nicht vorhanden' } });
  expect(screen.getByText('Passen Sie die Suche oder die Filter an.')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Zurücksetzen' }));
  expect(names()).toEqual(['Mieter']);
});
