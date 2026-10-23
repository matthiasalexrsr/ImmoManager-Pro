import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import Dashboard from '../pages/Dashboard';
import { api } from '../api';
import { DEFAULT_LAYOUT, TILES, arrange, move, toggle } from '../features/dashboard/dashboardTiles';

vi.mock('../api', () => ({ api: { get: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key, locale: 'de-DE' }) }));
vi.mock('recharts', () => {
  const Container = ({ children }) => <div>{children}</div>;
  const Empty = () => null;
  return { ResponsiveContainer: Container, BarChart: Container, PieChart: Container, LineChart: Container, Bar: Container,
    Pie: Container, Cell: Empty, XAxis: Empty, YAxis: Empty, Tooltip: Empty, Legend: Empty, Line: Empty, CartesianGrid: Empty };
});

beforeEach(() => { vi.resetAllMocks(); api.get.mockImplementation(() => new Promise(() => {})); });
afterEach(cleanup);

const order = () => [...document.querySelectorAll('.dashboard-tile')].map(tile => tile.dataset.tile);

describe('dashboard tiles', () => {
  it('keeps a saved layout safe when tiles are added or removed later', () => {
    expect(arrange(undefined)).toEqual(DEFAULT_LAYOUT);
    const saved = { column_order: ['tasks', 'gone', 'inventory', 'tasks'], hidden_columns: ['reports', 'gone'] };
    const layout = arrange(saved);
    expect(layout.column_order).toHaveLength(TILES.length);
    expect(layout.column_order[0]).toBe('reports');                 // a tile missing from the saved order: default place
    expect(layout.column_order.indexOf('tasks')).toBeLessThan(layout.column_order.indexOf('inventory'));
    expect(layout.hidden_columns).toEqual(['reports']);
    expect(move(layout, layout.column_order[0], -1)).toBe(layout);
    expect(toggle(toggle(layout, 'finance'), 'finance').hidden_columns).toEqual(['reports']);
  });

  it('hides and reorders tiles from "Kacheln anpassen" and restores the default', () => {
    render(<MemoryRouter><Dashboard /></MemoryRouter>);
    expect(order()).toEqual(TILES.map(tile => tile.key));
    fireEvent.click(screen.getByRole('button', { name: 'Kacheln anpassen' }));
    const panel = screen.getByRole('region', { name: 'Kacheln anpassen' });
    fireEvent.click(within(panel).getByLabelText('Auswertungen und Finanzplanung'));
    fireEvent.click(within(panel).getByRole('button', { name: 'Offene Aufgaben nach oben' }));
    fireEvent.click(within(panel).getByRole('button', { name: 'Offene Aufgaben nach oben' }));
    expect(order()).not.toContain('reports');
    expect(order().indexOf('tasks')).toBeLessThan(order().indexOf('finance'));
    expect(order().indexOf('tasks')).toBeLessThan(order().indexOf('attention'));
    fireEvent.click(within(panel).getByRole('button', { name: 'Fertig' }));
    expect(screen.getByText(/Eine Kachel ist ausgeblendet/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Kacheln anpassen', expanded: false }));
    fireEvent.click(screen.getByRole('button', { name: 'Standard wiederherstellen' }));
    expect(order()).toEqual(TILES.map(tile => tile.key));
  });
});
