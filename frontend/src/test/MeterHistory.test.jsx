import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { api } from '../api';
import MeterHistory from '../features/meters/MeterHistory';

vi.mock('../api', () => ({ api: { get: vi.fn() } }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

const HISTORY = {
  meter: { id: 'm1', unit_id: 'u1', meter_type: 'cold_water', measure_unit: null, location: 'Keller', supplier: 'Stadtwerke Leipzig',
    contract_number: 'SW-1', contract_end_date: '2027-12-31', portal_url: 'https://portal.example/login', is_active: true },
  readings: [
    { id: 'r1', reading_date: '2024-07-01', value: 100.1, consumption: null, days: null, per_day: null, recorded_by: 'Hausmeister', notes: null, warning: null },
    { id: 'r2', reading_date: '2025-01-01', value: 150.3, consumption: 50.2, days: 184, per_day: 0.273, recorded_by: null, notes: 'Auszug', warning: null },
    { id: 'r3', reading_date: '2025-03-01', value: 10, consumption: -140.3, days: 59, per_day: -2.378, recorded_by: null, notes: null,
      warning: 'Stand kleiner als zuvor: Zählertausch, Überlauf oder Ablesefehler?' },
  ],
  years: [{ year: 2024, consumption: 50.2, covered_days: 184, complete: false }, { year: 2025, consumption: 0, covered_days: 0, complete: false }],
  contracts: [{ id: 'sc1', title: 'Wasser Nordhaus', provider: 'KWL', contract_number: 'W-9', customer_number: 'K-1',
    portal_url: 'https://kwl.example', href: '/service-contracts/sc1' }],
};

it('shows the readings with consumption, the years, the supply contracts and their portals', async () => {
  api.get.mockResolvedValue(HISTORY);
  const onEdit = vi.fn(); const onRecord = vi.fn();
  await act(async () => {
    render(<MemoryRouter><MeterHistory meterId="m1" meterLabel="WZ 4711" unitLabel="EG links" propertyName="Haus" propertyId="p1"
      onClose={() => {}} onEdit={onEdit} onRecord={onRecord} /></MemoryRouter>);
  });
  expect(api.get).toHaveBeenCalledWith('/meters/m1/history', expect.anything());
  expect(screen.getByRole('heading', { name: 'WZ 4711' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'EG links' })).toHaveAttribute('href', '/units/u1');
  const portals = screen.getAllByRole('link', { name: /Kundenportal des Anbieters öffnen/ });
  expect(portals.map(link => link.getAttribute('href'))).toEqual(['https://portal.example/login', 'https://kwl.example']);
  portals.forEach(link => { expect(link).toHaveAttribute('target', '_blank'); expect(link).toHaveAttribute('rel', 'noopener noreferrer'); });
  expect(screen.getByRole('link', { name: 'Wasser Nordhaus' })).toHaveAttribute('href', '/service-contracts/sc1');
  const readings = screen.getByRole('table', { name: /Ablesungen/ });
  const rows = within(readings).getAllByRole('row');
  expect(rows[1]).toHaveTextContent('01.03.2025');                     // newest first
  expect(rows[2]).toHaveTextContent('50,2');
  expect(rows[2]).toHaveTextContent('Auszug');
  expect(screen.getByRole('note')).toHaveTextContent('Zählertausch');
  expect(screen.getByRole('heading', { name: 'Verbrauch je Kalenderjahr (m³)' })).toBeInTheDocument();
  expect(screen.getByText(/Schraffiert/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Zähler bearbeiten' }));
  fireEvent.click(screen.getByRole('button', { name: '+ Ablesung erfassen' }));
  expect(onEdit).toHaveBeenCalled(); expect(onRecord).toHaveBeenCalled();
});

it('closes on Escape unless a form opened from it is on top', async () => {
  api.get.mockResolvedValue(HISTORY);
  const onClose = vi.fn();
  const { rerender } = render(<MemoryRouter><MeterHistory meterId="m1" meterLabel="WZ 4711" covered onClose={onClose} /></MemoryRouter>);
  await act(async () => {});
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(onClose).not.toHaveBeenCalled();
  rerender(<MemoryRouter><MeterHistory meterId="m1" meterLabel="WZ 4711" onClose={onClose} /></MemoryRouter>);
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(onClose).toHaveBeenCalled();
});
