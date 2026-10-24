import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import DataTable from '../components/DataTable';

vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => true, useAuth: () => null }));

beforeEach(() => { localStorage.clear(); sessionStorage.clear(); });
afterEach(() => cleanup());

const action = (label, onClick = vi.fn()) => ({ label, icon: <span>{label[0]}</span>, onClick });
const row = () => screen.getByRole('table').tBodies[0].rows[0];

describe('Zeilenaktionen', () => {
  it('zeigt bei vielen Aktionen die ersten drei und Bearbeiten, den Rest mit Beschriftung im Menü', () => {
    const occupants = vi.fn();
    const onDelete = vi.fn();
    render(<DataTable title="Verträge" columns={[{ key: 'number', label: 'Vertragsnr.' }]}
      data={[{ id: 'c1', number: 'MV-2023-046' }]} onEdit={vi.fn()} onDelete={onDelete}
      rowActions={() => [action('Dokumente'), action('Mietverlauf'), action('Brief schreiben'),
        action('Wohnungsgeberbestätigung'), action('Übergabe'), action('Kaution'), action('Bewohner', occupants)]} />);

    const cells = within(row());
    // the test setup shows translation keys for the shared button texts
    for (const name of ['Dokumente', 'Mietverlauf', 'Brief schreiben', 'ui.buttons.edit']) {
      expect(cells.getByRole('button', { name })).toBeInTheDocument();
    }
    expect(cells.queryByRole('button', { name: 'Kaution' })).toBeNull();
    expect(cells.queryByRole('button', { name: 'ui.buttons.delete' })).toBeNull();

    fireEvent.click(cells.getByRole('button', { name: 'Weitere Aktionen' }));
    const menu = screen.getByRole('menu', { name: 'Weitere Aktionen' });
    expect(within(menu).getAllByRole('menuitem').map(item => item.textContent))
      .toEqual(['WWohnungsgeberbestätigung', 'ÜÜbergabe', 'KKaution', 'BBewohner', 'ui.buttons.delete']);
    fireEvent.click(within(menu).getByRole('menuitem', { name: /Bewohner/ }));
    expect(occupants).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('menu')).toBeNull();

    fireEvent.click(cells.getByRole('button', { name: 'Weitere Aktionen' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'ui.buttons.delete' }));
    expect(onDelete).toHaveBeenCalledWith({ id: 'c1', number: 'MV-2023-046' });
  });

  it('closes the menu with Escape and gives the keyboard back to its button', () => {
    render(<DataTable title="Verträge" columns={[{ key: 'number', label: 'Vertragsnr.' }]}
      data={[{ id: 'c1', number: 'MV-1' }]} onEdit={vi.fn()} onDelete={vi.fn()}
      rowActions={() => ['A', 'B', 'C', 'D', 'E'].map(label => action(label))} />);
    const toggle = within(row()).getByRole('button', { name: 'Weitere Aktionen' });
    fireEvent.click(toggle);
    const items = screen.getAllByRole('menuitem');
    expect(items[0]).toHaveFocus();
    fireEvent.keyDown(items[0], { key: 'ArrowDown' });
    expect(items[1]).toHaveFocus();
    fireEvent.keyDown(items[1], { key: 'Escape' });
    expect(screen.queryByRole('menu')).toBeNull();
    expect(toggle).toHaveFocus();
  });

  it('lässt bis zu fünf Aktionen in der Zeile', () => {
    render(<DataTable title="Rechnungen" columns={[{ key: 'number', label: 'Nr.' }]}
      data={[{ id: 'i1', number: 'R-1' }]} onEdit={vi.fn()} onDelete={vi.fn()}
      rowActions={() => [action('Prüfen'), action('Kopieren'), action('Zahlung zuordnen')]} />);
    const cells = within(row());
    expect(cells.queryByRole('button', { name: 'Weitere Aktionen' })).toBeNull();
    expect(cells.getByRole('button', { name: 'ui.buttons.delete' })).toBeInTheDocument();
  });
});

describe('Spalteninhalt', () => {
  it('bricht eine Vertragsnummer nicht um, einen Namen schon', () => {
    render(<DataTable title="Mieten" columns={[{ key: 'number', label: 'Vertrag' }, { key: 'name', label: 'Mieter' }]}
      data={[{ id: 'c1', number: 'MV-2023-046', name: 'Nguyen Thi Winkler' }]} />);
    expect(within(row()).getByText('MV-2023-046')).toHaveClass('cell-nowrap');
    expect(within(row()).getByText('Nguyen Thi Winkler')).not.toHaveClass('cell-nowrap');
  });

  it('setzt den Sortierpfeil einer Zahlenspalte vor die Überschrift', () => {
    render(<DataTable title="Mieten" columns={[{ key: 'name', label: 'Mieter' }, { key: 'rent', label: 'Vereinbarte Miete', type: 'currency' }]}
      data={[{ id: 'c1', name: 'A', rent: 500 }]} />);
    // a no-break space keeps the arrow beside its word when the heading wraps
    expect(screen.getByRole('columnheader', { name: 'Vereinbarte Miete' }).textContent).toBe('↕\u00a0Vereinbarte Miete');
    expect(screen.getByRole('columnheader', { name: 'Mieter' }).textContent).toBe('Mieter\u00a0↕');
  });
});
