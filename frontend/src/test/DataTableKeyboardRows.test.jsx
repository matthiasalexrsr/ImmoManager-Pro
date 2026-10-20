import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import DataTable from '../components/DataTable';

beforeEach(() => localStorage.clear());
afterEach(() => cleanup());

const rows = [{ id: 'a', title: 'Vorgang A' }, { id: 'b', title: 'Vorgang B' }];
const columns = [{ key: 'title', label: 'Vorgang' }];

it('öffnet eine interaktive Tabellenzeile per Enter oder Leertaste', () => {
  const open = vi.fn();
  render(<DataTable title="Vorgänge" columns={columns} data={rows} onRowClick={open} />);
  const table = screen.getByRole('table', { name: 'Vorgänge' });
  const row = within(table).getByRole('row', { name: /Eintrag öffnen: Vorgang A/ });
  expect(row).toHaveAttribute('tabindex', '0');
  row.focus(); expect(row).toHaveFocus();
  fireEvent.keyDown(row, { key: 'Enter' });
  expect(open).toHaveBeenCalledWith(rows[0]);
  fireEvent.keyDown(row, { key: ' ' });
  expect(open).toHaveBeenCalledTimes(2);
});

it('tastaturbediente Schaltflächen in Tabellenzeilen lösen keine Zeilenöffnung aus', () => {
  const open = vi.fn(); const action = vi.fn();
  render(<DataTable title="Vorgänge" columns={columns} data={rows} onRowClick={open}
    rowActions={() => [{ label: 'Aktion', icon: '!', onClick: action }]} />);
  const row = screen.getByRole('row', { name: /Eintrag öffnen: Vorgang A/ });
  const button = within(row).getByRole('button', { name: 'Aktion' });
  fireEvent.keyDown(button, { key: 'Enter' });
  fireEvent.click(button);
  expect(action).toHaveBeenCalledOnce();
  expect(open).not.toHaveBeenCalled();
});

it('rein lesbare Tabellen erhalten keine zusätzlichen Tabstopps', () => {
  render(<DataTable title="Vorgänge" columns={columns} data={rows} />);
  const row = screen.getAllByRole('row')[1];
  expect(row).not.toHaveAttribute('tabindex');
  expect(row).not.toHaveAttribute('aria-label');
});

it('eine Zeilenaktion ohne Symbol zeigt ihre Beschriftung statt einer leeren Schaltfläche', () => {
  render(<DataTable title="Vorgänge" columns={columns} data={rows}
    rowActions={() => [{ label: 'Verlauf', onClick: vi.fn() }]} />);
  const button = within(screen.getAllByRole('row')[1]).getByRole('button', { name: 'Verlauf' });
  expect(button).toHaveTextContent('Verlauf');
});
